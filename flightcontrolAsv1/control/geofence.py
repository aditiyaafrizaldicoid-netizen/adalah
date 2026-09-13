"""
Geofence: batalkan misi otomatis kalau kapal keluar dari batas yang diizinkan.

Batasnya berupa KOTAK SEJAJAR SUMBU — satu titik pusat, satu lebar (timur-barat)
dan satu tinggi (utara-selatan), keduanya dalam meter dan diukur sisi ke sisi.
Pusatnya, kalau tidak diisi, diambil dari posisi kapal SAAT MISI DIMULAI.

KENAPA KOTAK, BUKAN LINGKARAN (sejak versi ini):
    Danau dan arena lomba berbentuk persegi panjang. Lingkaran yang cukup besar
    untuk memuat seluruh arena mau tidak mau ikut memuat daratan di keempat
    sudutnya; lingkaran yang cukup kecil untuk menghindari daratan memotong
    ujung arena. Kotak bisa mengikuti bentuk perairannya.

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

   ⚠ PERHATIKAN BENTUKNYA BERBEDA: FENCE_RADIUS di ArduPilot tetap LINGKARAN dan
     tidak bisa dibuat kotak lewat parameter itu. Jadi setelah perubahan ini ada
     DUA batas dengan bentuk berbeda. Setel FENCE_RADIUS minimal sebesar setengah
     diagonal kotak ini (√(lebar² + tinggi²) / 2) supaya ArduPilot tidak lebih
     dulu bertindak di dalam kotak yang justru masih sah.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HANYA BERLAKU SAAT MISI OTONOM BERJALAN.
    _tick() langsung keluar kalau mission_engine.status != "RUNNING". Kapal yang
    dikemudikan MANUAL boleh keluar batas sejauh apa pun tanpa satu pun peringatan
    dari modul ini — yang memang disengaja (operator sedang memegang kendali),
    tapi berarti geofence ini BUKAN jaring pengaman untuk kemudi manual.

MENYIAPKAN (flightcontrolAsv1/.env di Mini PC):
    ASV_GEOFENCE_LEBAR_M=120      # bentangan timur-barat; 0 / kosong = NONAKTIF
    ASV_GEOFENCE_TINGGI_M=80      # bentangan utara-selatan
    ASV_GEOFENCE_LAT=             # opsional; kosong = pusat diambil saat misi mulai
    ASV_GEOFENCE_LON=

    ASV_GEOFENCE_RADIUS_M=60      # USANG. Masih dibaca demi Mini PC yang .env-nya
                                  # belum diperbarui: jadi kotak 2R × 2R. Tanpa
                                  # ini, kapal yang sudah dipasang di lapangan akan
                                  # diam-diam boot TANPA geofence sama sekali.
"""

import math
import os
import threading
import time

from control.geodesy import margin_kotak_m, posisi_masuk_akal


class GeofenceMonitor:
    """Pantau posisi kapal; batalkan misi begitu keluar batas kotak."""

    # Lama pelanggaran harus bertahan sebelum misi dibatalkan. Cukup panjang untuk
    # menelan satu-dua pembacaan GPS yang melenceng, cukup pendek supaya kapal tidak
    # sempat jauh — pada 1 m/s, 2 detik berarti sekitar 2 meter tambahan.
    CONFIRM_SEC = 2.0

    # Kapal harus masuk kembali SEDALAM ini dari sisi kotak sebelum pelanggaran
    # dianggap berakhir. Tanpa histeresis ini, kapal yang mengambang tepat di garis
    # batas akan memicu peringatan berulang-ulang.
    HYSTERESIS_M = 3.0

    POLL_SEC = 0.5

    def __init__(self, asv, mission_engine=None, lebar_m: float = None,
                 tinggi_m: float = None, center_lat: float = None,
                 center_lon: float = None, on_warning=None):
        """
        :param asv: ASVController.
        :param mission_engine: MissionEngine yang akan di-abort saat batas dilanggar.
        :param lebar_m: bentangan TIMUR-BARAT (meter, penuh). None/0 = nonaktif.
        :param tinggi_m: bentangan UTARA-SELATAN (meter, penuh). None = ikut lebar
                         (kotak bujur sangkar).
        :param center_lat/lon: pusat batas. None = diambil saat misi dimulai.
        :param on_warning: callback(level, code, message) ke base station.
        """
        self.asv = asv
        self.mission_engine = mission_engine
        self._on_warning = on_warning

        if lebar_m is None:
            lebar_m = self._env_float("ASV_GEOFENCE_LEBAR_M", 0.0)
        if tinggi_m is None:
            tinggi_m = self._env_float("ASV_GEOFENCE_TINGGI_M", 0.0)

        # Mini PC yang .env-nya masih dari versi lingkaran. Tanpa jalur ini kapal
        # yang sudah terpasang di lapangan akan boot TANPA geofence sama sekali,
        # dan tidak ada apa pun di layar yang menunjukkan bahwa pagar hilang.
        if lebar_m <= 0 and tinggi_m <= 0:
            radius_lama = self._env_float("ASV_GEOFENCE_RADIUS_M", 0.0)
            if radius_lama > 0:
                lebar_m = tinggi_m = radius_lama * 2.0
                print(f"[Geofence] ASV_GEOFENCE_RADIUS_M={radius_lama:.0f} (usang) "
                      f"dibaca sebagai kotak {lebar_m:.0f} × {tinggi_m:.0f} m. "
                      f"Perbarui .env ke ASV_GEOFENCE_LEBAR_M/TINGGI_M.")

        # Hanya satu sisi yang diisi = bujur sangkar. Menganggapnya nonaktif akan
        # membuang batas yang jelas-jelas diniatkan operator.
        if lebar_m > 0 and tinggi_m <= 0:
            tinggi_m = lebar_m
        elif tinggi_m > 0 and lebar_m <= 0:
            lebar_m = tinggi_m

        self.lebar_m = float(lebar_m or 0.0)
        self.tinggi_m = float(tinggi_m or 0.0)

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
        # Dimatikan operator dari peta — beda dari ukuran 0. Lihat configure().
        self._dimatikan_operator = False

    @staticmethod
    def _env_float(nama: str, default: float) -> float:
        try:
            return float(os.getenv(nama, "") or default)
        except (TypeError, ValueError):
            return default

    @property
    def enabled(self) -> bool:
        return (self.lebar_m > 0 and self.tinggi_m > 0
                and not self._dimatikan_operator)

    @property
    def diagonal_m(self) -> float:
        """
        Jarak pusat ke sudut terjauh. Inilah angka minimum yang pantas dipakai
        untuk FENCE_RADIUS di ArduPilot — lihat catatan bentuk di atas modul.
        """
        return math.hypot(self.lebar_m, self.tinggi_m) / 2.0

    def set_mission_engine(self, mission_engine):
        self.mission_engine = mission_engine

    def configure(self, enabled=None, lat=None, lon=None,
                  lebar_m=None, tinggi_m=None) -> str:
        """
        Ubah batas saat kapal SEDANG BERJALAN — dipakai saat operator menggambarnya
        di peta base station.

        Nilai yang None dibiarkan apa adanya, sehingga perintah boleh mengirim
        sebagian field saja (mis. cuma lebar).

        Mematikan geofence TIDAK menghapus pusat & ukuran yang sudah diatur: operator
        sering menonaktifkannya sementara saat menguji sesuatu, dan kehilangan batas
        yang sudah susah payah digambar di peta setiap kali itu terjadi bukan sesuatu
        yang bisa dimaafkan di tengah lomba.

        Return ringkasan untuk di-log/dikirim balik.
        """
        if lebar_m is not None:
            try:
                self.lebar_m = max(0.0, float(lebar_m))
            except (TypeError, ValueError):
                pass

        if tinggi_m is not None:
            try:
                self.tinggi_m = max(0.0, float(tinggi_m))
            except (TypeError, ValueError):
                pass

        if lat is not None and lon is not None and posisi_masuk_akal(lat, lon):
            self.center = (float(lat), float(lon))
            self._pusat_tetap = True

        if enabled is not None:
            self._dimatikan_operator = not bool(enabled)

        # Pelanggaran yang sedang dihitung dilupakan: batas baru berarti penilaian baru.
        self._melanggar_sejak = None
        self._sudah_membatalkan = False

        ringkas = (f"kotak {self.lebar_m:.0f} × {self.tinggi_m:.0f} m"
                   + (f", pusat {self.center[0]:.6f},{self.center[1]:.6f}" if self.center
                      else ", pusat diambil saat misi mulai")
                   + (" — DIMATIKAN operator" if self._dimatikan_operator else ""))
        print(f"[Geofence] Diperbarui dari base station: {ringkas}")
        return ringkas

    def start(self):
        if self._is_running:
            return
        # Thread TETAP dijalankan walau saat boot geofence belum aktif: operator
        # bisa menyalakannya dari peta kapan saja, dan memaksa restart kapal untuk
        # itu adalah friksi yang tidak perlu di tengah lomba. _tick() sendiri yang
        # tidak melakukan apa-apa selama enabled masih False.
        self._is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="GeofenceThread")
        self._thread.start()
        if self.enabled:
            asal = (f"pusat tetap {self.center[0]:.6f},{self.center[1]:.6f}"
                    if self._pusat_tetap else "pusat diambil saat misi dimulai")
            print(f"[Geofence] Aktif — kotak {self.lebar_m:.0f} × {self.tinggi_m:.0f} m "
                  f"(T-B × U-S), {asal}.")
            print(f"[Geofence] Setel FENCE_RADIUS ArduPilot ≥ {self.diagonal_m:.0f} m "
                  f"— bentuknya lingkaran, jadi harus memuat sudut kotak ini.")
        else:
            print("[Geofence] Belum aktif — bisa dinyalakan dari peta base station "
                  "tanpa perlu restart kapal.")

    def stop(self):
        self._is_running = False

    # ------------------------------------------------------------------ #

    def margin_m(self, lat, lon) -> float:
        """
        Seberapa dalam kapal di dalam batas (meter). Negatif = di luar.
        Satu-satunya tempat bentuk batas diputuskan — lihat geodesy.margin_kotak_m.
        """
        return margin_kotak_m(self.center[0], self.center[1],
                              self.lebar_m, self.tinggi_m, lat, lon)

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
                  f"(kotak {self.lebar_m:.0f} × {self.tinggi_m:.0f} m).")
            return True, ""

        if posisi_masuk_akal(lat, lon):
            margin = self.margin_m(lat, lon)
            if margin < 0:
                pesan = (f"Kapal sudah {-margin:.0f} m DI LUAR batas "
                         f"(kotak {self.lebar_m:.0f} × {self.tinggi_m:.0f} m) "
                         f"SEBELUM misi dimulai.")
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
        if not self.enabled:
            return
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

        margin = self.margin_m(lat, lon)

        if margin >= self.HYSTERESIS_M:
            self._melanggar_sejak = None
            return
        if margin >= 0:
            return   # di pita histeresis — jangan ubah apa pun

        if self._melanggar_sejak is None:
            self._melanggar_sejak = time.time()
            print(f"[Geofence] ⚠️ Kapal di luar batas ({-margin:.0f} m dari sisi "
                  f"terdekat) — menunggu konfirmasi {self.CONFIRM_SEC:.0f}s...")
            return
        if (time.time() - self._melanggar_sejak) < self.CONFIRM_SEC:
            return
        if self._sudah_membatalkan:
            return

        self._sudah_membatalkan = True
        self._batalkan(-margin)

    def _batalkan(self, keluar_m: float):
        """Batalkan misi. TIDAK disarm dan TIDAK memindah sumber kendali."""
        try:
            self.mission_engine.abort_mission()
        except Exception as e:
            print(f"[Geofence] Gagal membatalkan misi: {e}")

        pesan = (f"⛔ GEOFENCE: kapal {keluar_m:.0f} m di luar batas "
                 f"(kotak {self.lebar_m:.0f} × {self.tinggi_m:.0f} m). Misi "
                 f"DIBATALKAN. Kapal tidak di-disarm — pindahkan kendali ke remote "
                 f"untuk membawanya pulang.")
        print(f"[Geofence] {pesan}")
        self._warn("critical", "GEOFENCE_DILANGGAR", pesan)

    def _warn(self, level: str, code: str, message: str):
        if not self._on_warning:
            return
        try:
            self._on_warning(level, code, message)
        except Exception as e:
            print(f"[Geofence] Gagal mengirim peringatan: {e}")
