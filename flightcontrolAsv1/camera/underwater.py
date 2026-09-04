"""
Kamera bawah air — sumber foto khusus untuk box biru.

Terpisah total dari VideoStreamer (kamera permukaan). Kamera permukaan mengalir
terus ke dashboard dan menyuapi seluruh deteksi YOLO; kamera ini tidak melakukan
keduanya. Ia hanya menyediakan SATU frame terbaru kapan pun diminta.

KENAPA THREAD YANG TERUS BERJALAN, BUKAN DIBUKA SAAT DIBUTUHKAN:
    Membuka perangkat UVC butuh ratusan milidetik sampai beberapa detik (negosiasi
    format, auto-exposure yang belum mengunci). Mode foto "moving" tidak berhenti
    sama sekali — pada saat kamera akhirnya siap, box-nya sudah lewat. Membiarkan
    kamera terbuka membuat foto tersedia seketika.

    Ongkosnya bandwidth USB, dan itu ditekan lewat resolusi & FPS yang diatur
    terpisah dari kamera permukaan. Kamera ini tidak perlu 25 FPS; ia cuma perlu
    punya frame yang segar saat shutter diminta.

KENAPA FRAME TERUS DIBACA MESKI TIDAK DIPAKAI:
    Driver V4L2 menyimpan antrean frame. Kalau read() hanya dipanggil saat memotret,
    yang keluar adalah frame LAMA dari antrean — foto pemandangan beberapa detik
    yang lalu, yang tampak sah dan tidak mungkin dibedakan setelahnya. Membaca terus
    menerus menjaga antrean itu tetap kosong.
"""
import os
import threading
import time

try:
    import cv2
except ImportError:  # pragma: no cover - hanya di mesin tanpa OpenCV
    cv2 = None


class UnderwaterCamera:
    """Menjaga satu frame terbaru dari kamera bawah air."""

    # Frame yang lebih tua dari ini dianggap TIDAK ADA.
    #
    # Ini soal USIA frame, BUKAN isinya. Air keruh, gelap, atau kosong melompong
    # tetap frame yang sah dan tetap difoto — kamera ini tidak pernah menilai
    # apa yang terlihat. Yang ditolak hanya frame yang sudah kedaluwarsa.
    #
    # Kamera yang membeku (kabel longgar, perangkat hilang) tetap menyimpan frame
    # terakhirnya di memori, dan frame itu akan tersimpan sebagai "foto box biru"
    # padahal isinya pemandangan menit-menit sebelumnya. Foto basi jauh lebih buruk
    # daripada tidak ada foto: yang satu ketahuan, yang lain tidak.
    UMUR_MAKS_DETIK = 2.0

    # Jeda sebelum mencoba membuka ulang perangkat yang gagal.
    JEDA_COBA_ULANG_DETIK = 3.0

    def __init__(self, index, width=1280, height=720, fps=5, umur_maks_detik=None):
        self.index = index
        self.width = int(width)
        self.height = int(height)
        self.fps = max(1, int(fps))
        # Bisa dilonggarkan lewat .env: di air keruh dan cahaya minim, exposure
        # otomatis bisa memperlambat kamera jauh di bawah fps yang diminta.
        if umur_maks_detik is not None:
            self.UMUR_MAKS_DETIK = float(umur_maks_detik)

        self._cap = None
        self._frame = None
        self._frame_at = 0.0
        self._lock = threading.Lock()
        self._thread = None
        self._jalan = False
        self._gagal_terakhir_log = 0.0

    # ── Siklus hidup ────────────────────────────────────────────────────────

    def start(self):
        if self._jalan or cv2 is None:
            if cv2 is None:
                print("[Underwater] ⚠️ OpenCV tidak tersedia — kamera bawah air mati.")
            return
        self._jalan = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"[Underwater] 🌊 Kamera bawah air dijalankan pada index {self.index} "
              f"({self.width}x{self.height} @ {self.fps}fps).")

    def stop(self):
        self._jalan = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._tutup()

    # ── Status ──────────────────────────────────────────────────────────────

    def is_ok(self) -> bool:
        """True kalau ada frame yang cukup segar untuk dipakai memotret."""
        with self._lock:
            return (self._frame is not None
                    and (time.time() - self._frame_at) <= self.UMUR_MAKS_DETIK)

    def umur_frame_detik(self) -> float:
        """Usia frame terakhir. Besar sekali kalau belum pernah ada frame."""
        with self._lock:
            if self._frame is None:
                return float("inf")
            return time.time() - self._frame_at

    # ── Pengambilan frame ───────────────────────────────────────────────────

    def ambil_frame(self):
        """
        Salinan frame terbaru, atau None kalau tidak ada yang cukup segar.

        Mengembalikan SALINAN: pemanggil menggambari frame-nya (overlay geo-tag),
        dan menggambari buffer yang sama yang sedang ditulis thread pembaca akan
        merusak foto berikutnya.
        """
        with self._lock:
            if self._frame is None:
                return None
            if (time.time() - self._frame_at) > self.UMUR_MAKS_DETIK:
                return None
            return self._frame.copy()

    # ── Internal ────────────────────────────────────────────────────────────

    def _buka(self) -> bool:
        try:
            cap = cv2.VideoCapture(self.index)
            if not cap.isOpened():
                cap.release()
                return False
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            # Antrean sependek mungkin: yang dibutuhkan selalu frame TERBARU,
            # bukan frame terlama yang masih tersimpan driver.
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass  # tidak semua backend mendukung; bukan alasan gagal
            self._cap = cap
            print(f"[Underwater] ✅ Kamera bawah air index {self.index} terbuka.")
            return True
        except Exception as e:
            self._log_gagal(f"gagal membuka index {self.index}: {e}")
            return False

    def _tutup(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _log_gagal(self, pesan):
        """Batasi banjir log: perangkat yang hilang gagal 5x per detik."""
        now = time.time()
        if now - self._gagal_terakhir_log > 5.0:
            self._gagal_terakhir_log = now
            print(f"[Underwater] ⚠️ {pesan}")

    def _loop(self):
        jeda = 1.0 / self.fps
        while self._jalan:
            if self._cap is None:
                if not self._buka():
                    time.sleep(self.JEDA_COBA_ULANG_DETIK)
                    continue

            try:
                ok, frame = self._cap.read()
            except Exception as e:
                ok, frame = False, None
                self._log_gagal(f"pembacaan error: {e}")

            if not ok or frame is None:
                # Perangkat dicabut atau tersendat. Ditutup lalu dibuka lagi —
                # frame lama SENGAJA tidak dihapus di sini; pengecekan umur di
                # ambil_frame() yang menolaknya, jadi satu frame gagal tidak
                # langsung menghanguskan foto yang sedang diminta.
                self._log_gagal(f"tidak ada frame dari index {self.index}")
                self._tutup()
                time.sleep(self.JEDA_COBA_ULANG_DETIK)
                continue

            with self._lock:
                self._frame = frame
                self._frame_at = time.time()

            time.sleep(jeda)

        self._tutup()


def dari_env():
    """
    Bangun kamera bawah air dari .env, atau None kalau tidak dipasang.

    Tidak diaktifkan diam-diam: tanpa ASV_UNDERWATER_CAMERA_INDEX, fitur ini mati
    total dan foto box biru tetap memakai kamera permukaan seperti sebelumnya.
    Kapal yang kamera bawah airnya belum terpasang tidak boleh berubah perilakunya
    hanya karena kodenya sudah ada.
    """
    raw = os.getenv("ASV_UNDERWATER_CAMERA_INDEX", "").strip()
    if raw == "":
        return None
    try:
        index = int(raw)
    except ValueError:
        print(f"[Underwater] ⚠️ ASV_UNDERWATER_CAMERA_INDEX='{raw}' bukan angka — "
              f"kamera bawah air tidak diaktifkan.")
        return None

    def _int_env(nama, default):
        try:
            return int(os.getenv(nama, "").strip() or default)
        except ValueError:
            return default

    def _float_env(nama, default):
        try:
            return float(os.getenv(nama, "").strip() or default)
        except ValueError:
            return default

    return UnderwaterCamera(
        index=index,
        width=_int_env("ASV_UNDERWATER_WIDTH", 1280),
        height=_int_env("ASV_UNDERWATER_HEIGHT", 720),
        fps=_int_env("ASV_UNDERWATER_FPS", 5),
        umur_maks_detik=_float_env("ASV_UNDERWATER_MAX_AGE_SEC",
                                   UnderwaterCamera.UMUR_MAKS_DETIK),
    )
