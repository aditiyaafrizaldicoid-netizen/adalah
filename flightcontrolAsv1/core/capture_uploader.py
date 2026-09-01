"""
Pengirim foto misi dari kapal ke base station.

KENAPA LEWAT ANTREAN, BUKAN LANGSUNG DIKIRIM:
    capture_now() dipanggil dari process_and_control() di main.py, yang berjalan di
    thread yang SAMA dengan pemrosesan YOLO dan pengiriman RC override — ~25 kali per
    detik. Satu POST HTTP yang menunggu jaringan lambat di sana akan menahan seluruh
    loop kendali: selama itu tidak ada perintah kemudi baru yang dikirim ke Pixhawk,
    dan kapal terus meluncur dengan perintah terakhir. Foto tidak pernah cukup penting
    untuk membuat kapal berhenti dikendalikan.

    Jadi pemanggil hanya menaruh path berkas ke antrean (tidak pernah memblokir), dan
    satu thread latar yang mengirimnya. Kalau base station sedang tidak terjangkau,
    foto tetap aman tersimpan di disk kapal — persis seperti sebelum modul ini ada.
"""

import os
import queue
import threading
import time

import requests


class CaptureUploader:
    """Kirim foto misi + sidecar geo-tag-nya ke base station, di latar belakang."""

    # Foto dicoba ulang beberapa kali: WiFi di atas air putus-nyambung, dan kegagalan
    # sesaat tepat saat shutter ditekan tidak boleh berarti fotonya hilang dari
    # dashboard sampai run selesai.
    MAX_ATTEMPTS = 3
    RETRY_DELAY_SEC = 4.0

    # Antrean dibatasi supaya kegagalan jaringan yang panjang tidak menumpuk tanpa
    # batas di RAM Mini PC. Realistisnya satu run cuma menghasilkan beberapa foto.
    MAX_QUEUE = 32

    def __init__(self, upload_url: str = None, token: str = None):
        # Sama seperti alamat WS & video: WAJIB dari .env, tidak boleh hardcode
        # localhost — di kapal, backend ada di base station.
        self.upload_url = upload_url or os.getenv("ASV_CAPTURE_URL", "").strip()
        self.token = token if token is not None else os.getenv("ASV_WS_TOKEN", "").strip()

        self._queue: "queue.Queue[str]" = queue.Queue(maxsize=self.MAX_QUEUE)
        self._is_running = False
        self._thread = None
        self._session = None

        if not self.upload_url:
            print("[CaptureUploader] ⚠️ ASV_CAPTURE_URL belum diisi — foto misi tetap "
                  "tersimpan di kapal tapi TIDAK akan muncul di dashboard.")

    def start(self):
        if self._is_running or not self.upload_url:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="CaptureUploaderThread")
        self._thread.start()
        print(f"[CaptureUploader] Siap mengirim foto misi ke {self.upload_url}")

    def stop(self):
        self._is_running = False

    def enqueue(self, image_path: str):
        """
        Antrekan satu foto untuk dikirim. TIDAK PERNAH memblokir pemanggil.

        Aman dipanggil dengan None (capture_now() mengembalikan None saat foto gagal
        disimpan), sehingga pemanggil tidak perlu memeriksanya sendiri tiap frame.
        """
        if not image_path or not self.upload_url:
            return
        try:
            self._queue.put_nowait(image_path)
        except queue.Full:
            # Membuang foto TERBARU, bukan yang terlama: yang sudah antre lebih dulu
            # sudah menunggu lebih lama dan kemungkinan besar lebih dekat berhasil.
            print("[CaptureUploader] ⚠️ Antrean penuh — foto ini tidak dikirim "
                  f"(tetap tersimpan di kapal): {os.path.basename(image_path)}")

    def _loop(self):
        while self._is_running:
            try:
                path = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._send_with_retry(path)
            except Exception as e:
                print(f"[CaptureUploader] Error tak terduga saat mengirim foto: {e}")

    # Hasil satu percobaan kirim.
    OK = "ok"           # berhasil
    RETRY = "retry"     # gagal sesaat (jaringan, 5xx) — layak diulang
    GIVE_UP = "give_up" # permintaannya sendiri yang salah — mengulang tidak menolong

    def _send_with_retry(self, image_path: str):
        nama = os.path.basename(image_path)
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            if not self._is_running:
                return
            hasil = self._send_once(image_path, nama)
            if hasil == self.OK:
                print(f"[CaptureUploader] 📤 Foto terkirim ke base station: {nama}")
                return
            if hasil == self.GIVE_UP:
                print(f"[CaptureUploader] ⚠️ {nama} tidak dikirim ulang — "
                      f"permintaannya ditolak, bukan gangguan jaringan. "
                      f"Berkasnya tetap ada di kapal.")
                return
            if attempt < self.MAX_ATTEMPTS:
                time.sleep(self.RETRY_DELAY_SEC)
        print(f"[CaptureUploader] ⚠️ Gagal mengirim {nama} setelah "
              f"{self.MAX_ATTEMPTS} percobaan. Berkasnya tetap ada di kapal.")

    def _send_once(self, image_path: str, nama: str) -> str:
        try:
            with open(image_path, "rb") as f:
                gambar = f.read()
        except OSError as e:
            print(f"[CaptureUploader] Tidak bisa membaca {nama}: {e}")
            return self.GIVE_UP   # berkasnya sendiri bermasalah

        # Sidecar geo-tag ditulis camera/geotag.py berdampingan dengan gambarnya.
        # Kalau tidak ada, foto tetap dikirim: gambar tanpa metadata masih jauh lebih
        # berguna daripada tidak ada gambar sama sekali.
        meta = ""
        sidecar = os.path.splitext(image_path)[0] + ".json"
        try:
            with open(sidecar, "r", encoding="utf-8") as f:
                meta = f.read()
        except OSError:
            pass

        try:
            if self._session is None:
                self._session = requests.Session()
                if self.token:
                    self._session.headers["X-ASV-Token"] = self.token
            resp = self._session.post(
                self.upload_url,
                files={"photo": (nama, gambar, "image/jpeg")},
                data={"meta": meta},
                timeout=(3.0, 10.0),
            )
            if resp.status_code == 200:
                return self.OK
            print(f"[CaptureUploader] Base station menolak {nama}: "
                  f"HTTP {resp.status_code} {resp.text[:120]}")
            # 4xx = permintaannya sendiri salah (nama berkas ditolak, token keliru).
            # Mengirim ulang isi yang persis sama akan ditolak persis sama juga.
            if 400 <= resp.status_code < 500:
                return self.GIVE_UP
            return self.RETRY
        except Exception as e:
            print(f"[CaptureUploader] Gagal mengirim {nama}: {e}")
            return self.RETRY
