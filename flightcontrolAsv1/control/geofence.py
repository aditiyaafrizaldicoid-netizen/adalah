"""
Geofence: batalkan misi otomatis kalau kapal keluar dari batas yang diizinkan.

Batasnya berupa LINGKARAN — satu titik pusat dan satu jari-jari. Pusatnya, kalau
tidak diisi, diambil dari posisi kapal SAAT MISI DIMULAI. Jadi yang perlu disetel
biasanya cuma satu angka: jari-jarinya.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EMPAT KEPUTUSAN YANG MENENTUKAN APAKAH INI MENOLONG ATAU MALAH MERUSAK

1. POSISI TIDAK MASUK AKAL TIDAK PERNAH MEMICU PEMBATALAN.
   Sebelum GPS mengunci, kapal melaporkan lat/lon 0,0 — titik di Teluk Guinea,
   ribuan kilometer dari mana pun. Geofence yang mempercayainya akan membatalkan
   SETIAP misi sebelum sempat berjalan, dan penyebabnya akan terlihat seperti
   "fitur misi rusak". Lihat geodesy.posisi_masuk_akal().

2. PELANGGARAN HARUS BERTAHAN DULU.
   Satu pembacaan GPS yang melenceng tidak boleh menghentikan lomba. Kapal harus
   berada di luar batas selama CONFIRM_SEC berturut-turut.

3. MEMBATALKAN MISI SAJA — TIDAK DISARM, TIDAK MEMINDAH SUMBER KENDALI.
   Setelah kapal keluar batas, yang dibutuhkan operator adalah MENGEMUDIKANNYA
   PULANG. Disarm justru mengambil kemampuan itu. Dan memaksa sumber kendali ke
   remote akan berkelahi dengan switch fisik di remote (lihat rc_source_switch.py,
   posisi switch selalu menang) — kapal akan berkedip antar sumber. Jadi: misi
   dibatalkan, kapal ditahan netral, operator yang memutuskan langkah berikutnya.

4. INI LAPIS DALAM, BUKAN SATU-SATUNYA.
   Geofence ini hidup di Mini PC. Kalau Mini PC-nya sendiri yang hang, ia ikut
   diam. Pagar yang sesungguhnya tetap FENCE_ENABLE/FENCE_RADIUS/FENCE_ACTION di
   ArduPilot, yang berjalan di Flight Controller dan tidak peduli mini PC hidup
   atau mati. Yang di sini menghentikan MISI-nya; yang di sana menyelamatkan
   KAPAL-nya. Pasang keduanya.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MENYIAPKAN (flightcontrolAsv1/.env di Mini PC):
    ASV_GEOFENCE_RADIUS_M=60      # 0 / kosong = fitur NONAKTIF
    ASV_GEOFENCE_LAT=             # opsional; kosong = pusat diambil saat misi mulai
    ASV_GEOFENCE_LON=
"""

import os
import threading
import time

from control.geodesy import haversine_m, posisi_masuk_akal


class GeofenceMonitor:
    """Pantau posisi kapal; batalkan misi begitu keluar batas."""

    # Lama pelanggaran harus bertahan sebelum misi dibatalkan. Cukup panjang untuk
    # menelan satu-dua pembacaan GPS yang melenceng, cukup pendek supaya kapal tidak
    # sempat jauh — pada 1 m/s, 2 detik berarti sekitar 2 meter tambahan.
    CONFIRM_SEC = 2.0

    # Jarak masuk kembali harus lebih dalam dari batas sebelum pelanggaran dianggap
    # berakhir. Tanpa histeresis ini, kapal yang mengambang tepat di garis batas akan
    # memicu peringatan berulang-ulang.
    HYSTERESIS_M = 3.0

    POLL_SEC = 0.5

    def __init__(self, asv, mission_engine=None, radius_m: float = None,
                 center_lat: float = None, center_lon: float = None,
                 on_warning=None):
        """
        :param asv: ASVController.
        :param mission_engine: MissionEngine yang akan di-abort saat batas dilanggar.
        :param radius_m: jari-jari batas (meter). None/0 = fitur nonaktif.
        :param center_lat/lon: pusat batas. None = diambil saat misi dimulai.
        :param on_warning: callback(level, code, message) ke base station.
        """
        self.asv = asv
        self.mission_engine = mission_engine
        self._on_warning = on_warning

        if radius_m is None:
            radius_m = self._env_float("ASV_GEOFENCE_RADIUS_M", 0.0)
        self.radius_m = float(radius_m or 0.0)

        if center_lat is None:
            center_lat = self._env_float("ASV_GEOFENCE_LAT", 0.0)
        if center_lon is None:
            center_lon = self._env_float("ASV_GEOFENCE_LON", 0.0)
        # Pusat tetap dipakai HANYA kalau koordinatnya masuk akal; kalau tidak,
        # dibiarkan kosong supaya diambil dari posisi saat misi dimulai.
        if posisi_masuk_akal(center_lat, center_lon):
            self.center = (float(center_lat), float(center_lon))
            self._pusat_tetap = True
        else:
            self.center = None
            self._pusat_tetap = False

        self._is_running = False
        self._thread = None
        self._melanggar_sejak = None
        self._sudah_membatalkan = False
        self._lapor_gps_buruk = False

    @staticmethod
    def _env_float(nama: str, default: float) -> float:
        try:
            return float(os.getenv(nama, "") or default)
        except (TypeError, ValueError):
            return default

    @property
    def enabled(self) -> bool:
        return self.radius_m > 0

    def set_mission_engine(self, mission_engine):
        self.mission_engine = mission_engine

    def start(self):
        if self._is_running:
            return
        if not self.enabled:
            print("[Geofence] NONAKTIF (ASV_GEOFENCE_RADIUS_M belum diisi).")
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="GeofenceThread")
        self._thread.start()
        asal = (f"pusat tetap {self.center[0]:.6f},{self.center[1]:.6f}"
                if self._pusat_tetap else "pusat diambil saat misi dimulai")
        print(f"[Geofence] Aktif — jari-jari {self.radius_m:.0f} m, {asal}.")

    def stop(self):
        self._is_running = False

    # ------------------------------------------------------------------ #

    def on_mission_started(self):
        """
        Dipanggil saat misi mulai. Kunci pusat batas ke posisi kapal sekarang, dan
        lupakan pelanggaran run sebelumnya.

        Return (ok, pesan): ok=False berarti misi TIDAK layak dijalankan — mis.
        kapal sudah di luar batas sebelum berangkat.
        """
        self._melanggar_sejak = None
        self._sudah_membatalkan = False
        if not self.enabled:
            return True, ""

        lat, lon = self._posisi()
        if not self._pusat_tetap:
            if not posisi_masuk_akal(lat, lon):
                # Tidak menolak misi karena ini: GPS bisa saja mengunci beberapa
                # detik kemudian. Pusatnya akan diambil begitu posisi masuk akal.
                print("[Geofence] ⚠️ Posisi belum valid saat misi mulai — pusat batas "
                      "akan dikunci begitu GPS mengunci.")
                self.center = None
                return True, ""
            self.center = (lat, lon)
            print(f"[Geofence] Pusat batas dikunci di {lat:.6f}, {lon:.6f} "
                  f"(jari-jari {self.radius_m:.0f} m).")
            return True, ""

        if posisi_masuk_akal(lat, lon):
            jarak = haversine_m(lat, lon, *self.center)
            if jarak > self.radius_m:
                pesan = (f"Kapal sudah {jarak:.0f} m dari pusat batas "
                         f"(maks {self.radius_m:.0f} m) SEBELUM misi dimulai.")
                return False, pesan
        return True, ""

    def _posisi(self):
        t = self.asv.get_telemetry_dict()
        return t.get("lat"), t.get("lon")

    def _loop(self):
        while self._is_running:
            try:
                self._tick()
            except Exception as e:
                print(f"[Geofence] Error saat memeriksa batas: {e}")
            time.sleep(self.POLL_SEC)

    def _tick(self):
        me = self.mission_engine
        if me is None or me.status != "RUNNING":
            # Di luar misi, tidak ada yang perlu dibatalkan. Hitungan pelanggaran
            # dilupakan supaya run berikutnya dinilai dari nol.
            self._melanggar_sejak = None
            self._sudah_membatalkan = False
            return

        lat, lon = self._posisi()
        if not posisi_masuk_akal(lat, lon):
            # KUNCI: posisi tidak masuk akal TIDAK PERNAH dihitung sebagai
            # pelanggaran. Lihat catatan panjang di atas modul.
            if not self._lapor_gps_buruk:
                self._lapor_gps_buruk = True
                self._warn("warning", "GEOFENCE_GPS_TIDAK_VALID",
                           "Geofence tidak bisa memeriksa batas: posisi GPS belum "
                           "valid. Misi TIDAK dibatalkan — batas tidak dijaga sampai "
                           "GPS mengunci.")
            self._melanggar_sejak = None
            return
        self._lapor_gps_buruk = False

        # Pusat belum sempat dikunci saat misi mulai (GPS baru mengunci sekarang).
        if self.center is None:
            self.center = (lat, lon)
            print(f"[Geofence] Pusat batas dikunci menyusul di {lat:.6f}, {lon:.6f}.")
            return

        jarak = haversine_m(lat, lon, *self.center)

        if jarak <= self.radius_m - self.HYSTERESIS_M:
            self._melanggar_sejak = None
            return
        if jarak <= self.radius_m:
            return   # di pita histeresis — jangan ubah apa pun

        if self._melanggar_sejak is None:
            self._melanggar_sejak = time.time()
            print(f"[Geofence] ⚠️ Kapal di luar batas ({jarak:.0f} m > "
                  f"{self.radius_m:.0f} m) — menunggu konfirmasi {self.CONFIRM_SEC:.0f}s...")
            return
        if (time.time() - self._melanggar_sejak) < self.CONFIRM_SEC:
            return
        if self._sudah_membatalkan:
            return

        self._sudah_membatalkan = True
        self._batalkan(jarak)

    def _batalkan(self, jarak: float):
        """Batalkan misi. TIDAK disarm dan TIDAK memindah sumber kendali."""
        try:
            self.mission_engine.abort_mission()
        except Exception as e:
            print(f"[Geofence] Gagal membatalkan misi: {e}")

        pesan = (f"⛔ GEOFENCE: kapal {jarak:.0f} m dari pusat batas "
                 f"(maks {self.radius_m:.0f} m). Misi DIBATALKAN. Kapal tidak "
                 f"di-disarm — pindahkan kendali ke remote untuk membawanya pulang.")
        print(f"[Geofence] {pesan}")
        self._warn("critical", "GEOFENCE_DILANGGAR", pesan)

    def _warn(self, level: str, code: str, message: str):
        if not self._on_warning:
            return
        try:
            self._on_warning(level, code, message)
        except Exception as e:
            print(f"[Geofence] Gagal mengirim peringatan: {e}")
