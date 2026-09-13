"""
Uji geofence kapal — bentuk KOTAK, dan penegakannya.

Jalankan:  make test-unit        (atau: python3 -m unittest discover -s tests -t .)

KENAPA UJI INI ADA SAMA SEKALI:
    Geofence adalah satu-satunya hal di kapal ini yang tugasnya MENGHENTIKAN
    sesuatu. Kalau ia salah, tidak ada yang berteriak: misi berjalan normal
    sampai kapal keluar batas dan tidak ada yang terjadi, atau — lebih buruk —
    misi dibatalkan di tengah lomba oleh batas yang dikira aman. Dua-duanya baru
    ketahuan di air, saat sudah tidak ada waktu memeriksa apa pun.

    Sebelum berkas ini, seluruh modul geofence tidak punya satu pun uji.

Yang TIDAK diuji di sini: thread-nya. _loop() cuma pembungkus tidur-dan-panggil;
yang diuji adalah _tick(), supaya setiap kasus berjalan pasti dan seketika alih-
alih menunggu jam dinding.
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control import geofence as geofence_mod
from control.geofence import GeofenceMonitor
from control.geodesy import kotak_batas, margin_kotak_m, haversine_m

LAT = -7.9215169
LON = 112.5973649


# ── Tiruan seperlunya ───────────────────────────────────────────────────────

class AsvPalsu:
    def __init__(self, lat=LAT, lon=LON):
        self.lat, self.lon = lat, lon

    def get_telemetry_dict(self):
        return {"lat": self.lat, "lon": self.lon}

    def pindah(self, lat, lon):
        self.lat, self.lon = lat, lon


class MisiPalsu:
    def __init__(self, status="RUNNING"):
        self.status = status
        self.jumlah_abort = 0

    def abort_mission(self):
        self.jumlah_abort += 1
        self.status = "ABORTED"


class JamPalsu:
    """Pengganti modul `time` di dalam geofence.py."""
    def __init__(self):
        self.sekarang = 1_700_000_000.0

    def time(self):
        return self.sekarang

    def sleep(self, _):
        pass

    def maju(self, detik):
        self.sekarang += detik


def geser_utara(lat, meter):
    """Lintang setelah bergerak `meter` ke utara."""
    return lat + (meter / 6371000.0) * (180.0 / math.pi)


def geser_timur(lat, lon, meter):
    """Bujur setelah bergerak `meter` ke timur, pada lintang `lat`."""
    return lon + (meter / (6371000.0 * math.cos(math.radians(lat)))) * (180.0 / math.pi)


class UjiGeofence(unittest.TestCase):
    def setUp(self):
        self.jam = JamPalsu()
        self._jam_asli = geofence_mod.time
        geofence_mod.time = self.jam

        self.asv = AsvPalsu()
        self.misi = MisiPalsu()
        self.peringatan = []

        # Env dibersihkan: nilai nyata di mesin pengembang tidak boleh mengubah
        # hasil uji. Kotak 100 (T-B) × 60 (U-S), pusat di tengah danau.
        self._env_asli = {k: os.environ.pop(k, None) for k in (
            "ASV_GEOFENCE_LEBAR_M", "ASV_GEOFENCE_TINGGI_M",
            "ASV_GEOFENCE_RADIUS_M", "ASV_GEOFENCE_LAT", "ASV_GEOFENCE_LON")}

    def tearDown(self):
        geofence_mod.time = self._jam_asli
        for k, v in self._env_asli.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def buat(self, lebar=100.0, tinggi=60.0, pusat=(LAT, LON), **kw):
        return GeofenceMonitor(
            self.asv, mission_engine=self.misi,
            lebar_m=lebar, tinggi_m=tinggi,
            center_lat=pusat[0] if pusat else None,
            center_lon=pusat[1] if pusat else None,
            on_warning=lambda lv, c, m: self.peringatan.append((lv, c, m)),
            **kw)

    def tick_selama(self, gf, detik):
        """Jalankan _tick berulang sambil memajukan jam, seperti thread aslinya."""
        langkah = gf.POLL_SEC
        habis = 0.0
        while habis < detik:
            gf._tick()
            self.jam.maju(langkah)
            habis += langkah
        gf._tick()


# ── Geometri kotak ──────────────────────────────────────────────────────────

class UjiGeometriKotak(UjiGeofence):
    def test_margin_di_pusat_adalah_setengah_sisi_terpendek(self):
        # Kotak 100 × 60: dari pusat, sisi terdekat adalah utara/selatan (30 m).
        self.assertAlmostEqual(margin_kotak_m(LAT, LON, 100, 60, LAT, LON), 30.0, places=6)

    def test_tepat_di_dalam_dan_tepat_di_luar_sisi_utara(self):
        # Setengah tinggi = 30 m.
        d = margin_kotak_m(LAT, LON, 100, 60, geser_utara(LAT, 29.0), LON)
        self.assertAlmostEqual(d, 1.0, places=2)
        d = margin_kotak_m(LAT, LON, 100, 60, geser_utara(LAT, 31.0), LON)
        self.assertAlmostEqual(d, -1.0, places=2)

    def test_sisi_timur_memakai_setengah_lebar(self):
        # Setengah lebar = 50 m — beda dari tinggi, jadi sumbu tidak tertukar.
        d = margin_kotak_m(LAT, LON, 100, 60, LAT, geser_timur(LAT, LON, 49.0))
        self.assertAlmostEqual(d, 1.0, places=2)
        d = margin_kotak_m(LAT, LON, 100, 60, LAT, geser_timur(LAT, LON, 51.0))
        self.assertAlmostEqual(d, -1.0, places=2)

    def test_keluar_lewat_sudut_diukur_diagonal(self):
        # 3 m di luar utara DAN 4 m di luar timur → 5 m, bukan 4 m.
        lat = geser_utara(LAT, 33.0)
        lon = geser_timur(LAT, LON, 54.0)
        self.assertAlmostEqual(margin_kotak_m(LAT, LON, 100, 60, lat, lon), -5.0, places=2)

    def test_bentangan_bujur_melebar_mengikuti_lintang(self):
        # cos(lat) mengecil menjauhi khatulistiwa, jadi 100 m timur-barat butuh
        # lebih banyak DERAJAT bujur. Salah menghilangkan faktor ini membuat
        # kotak di lintang tinggi jauh lebih sempit dari yang diminta.
        di_khatulistiwa = kotak_batas(0.0, LON, 100, 60)
        di_lintang_60 = kotak_batas(60.0, LON, 100, 60)
        rentang_khat = di_khatulistiwa[3] - di_khatulistiwa[2]
        rentang_60 = di_lintang_60[3] - di_lintang_60[2]
        self.assertAlmostEqual(rentang_60 / rentang_khat, 2.0, places=3)

    def test_bentangan_lintang_tidak_tergantung_lintang(self):
        a = kotak_batas(0.0, LON, 100, 60)
        b = kotak_batas(60.0, LON, 100, 60)
        self.assertAlmostEqual(a[1] - a[0], b[1] - b[0], places=12)

    def test_kotak_simetris_terhadap_pusat(self):
        lat_min, lat_maks, lon_min, lon_maks = kotak_batas(LAT, LON, 100, 60)
        self.assertAlmostEqual((lat_min + lat_maks) / 2, LAT, places=12)
        self.assertAlmostEqual((lon_min + lon_maks) / 2, LON, places=12)

    def test_sisi_utara_selatan_benar_benar_60_meter(self):
        lat_min, lat_maks, _, _ = kotak_batas(LAT, LON, 100, 60)
        self.assertAlmostEqual(haversine_m(lat_min, LON, lat_maks, LON), 60.0, places=6)

    def test_sisi_timur_barat_benar_benar_100_meter(self):
        _, _, lon_min, lon_maks = kotak_batas(LAT, LON, 100, 60)
        self.assertAlmostEqual(haversine_m(LAT, lon_min, LAT, lon_maks), 100.0, places=3)


# ── Penegakan ───────────────────────────────────────────────────────────────

class UjiPenegakan(UjiGeofence):
    def test_di_dalam_batas_tidak_membatalkan_apa_pun(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 10), LON)
        self.tick_selama(gf, 10.0)
        self.assertEqual(self.misi.jumlah_abort, 0)

    def test_di_luar_batas_belum_cukup_lama_belum_membatalkan(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 40), LON)  # 10 m di luar
        gf._tick()
        self.jam.maju(gf.CONFIRM_SEC - 0.5)
        gf._tick()
        # Satu pembacaan GPS yang melenceng tidak boleh menghentikan lomba.
        self.assertEqual(self.misi.jumlah_abort, 0)

    def test_di_luar_batas_cukup_lama_membatalkan_misi(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 40), LON)
        self.tick_selama(gf, gf.CONFIRM_SEC + 1.0)
        self.assertEqual(self.misi.jumlah_abort, 1)
        self.assertTrue(any(c == "GEOFENCE_DILANGGAR" for _, c, _ in self.peringatan))

    def test_pembatalan_memakai_level_critical(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 40), LON)
        self.tick_selama(gf, gf.CONFIRM_SEC + 1.0)
        level = [lv for lv, c, _ in self.peringatan if c == "GEOFENCE_DILANGGAR"]
        self.assertEqual(level, ["critical"])

    def test_hanya_membatalkan_sekali(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 40), LON)
        self.tick_selama(gf, gf.CONFIRM_SEC + 10.0)
        self.assertEqual(self.misi.jumlah_abort, 1)

    def test_keluar_lewat_sudut_juga_membatalkan(self):
        # Sudut adalah tempat lingkaran dan kotak paling berbeda — posisi ini
        # ada DI DALAM lingkaran jari-jari 58 m, tapi di luar kotak 100 × 60.
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 35), geser_timur(LAT, LON, 45))
        self.tick_selama(gf, gf.CONFIRM_SEC + 1.0)
        self.assertEqual(self.misi.jumlah_abort, 1)

    def test_tidak_membatalkan_saat_misi_tidak_berjalan(self):
        gf = self.buat()
        self.misi.status = "IDLE"
        self.asv.pindah(geser_utara(LAT, 500), LON)
        self.tick_selama(gf, 10.0)
        self.assertEqual(self.misi.jumlah_abort, 0)

    def test_tidak_membatalkan_saat_ukuran_nol(self):
        gf = self.buat(lebar=0.0, tinggi=0.0)
        self.assertFalse(gf.enabled)
        self.asv.pindah(geser_utara(LAT, 500), LON)
        self.tick_selama(gf, 10.0)
        self.assertEqual(self.misi.jumlah_abort, 0)

    def test_tidak_membatalkan_setelah_dimatikan_operator(self):
        gf = self.buat()
        gf.configure(enabled=False)
        self.assertFalse(gf.enabled)
        self.asv.pindah(geser_utara(LAT, 500), LON)
        self.tick_selama(gf, 10.0)
        self.assertEqual(self.misi.jumlah_abort, 0)


class UjiGpsBuruk(UjiGeofence):
    def test_nol_nol_tidak_pernah_membatalkan(self):
        # Sebelum GPS mengunci kapal melaporkan 0,0 — Teluk Guinea, ribuan km
        # dari mana pun. Geofence yang mempercayainya membatalkan SETIAP misi
        # sebelum sempat berjalan, dan terlihat seperti "fitur misi rusak".
        gf = self.buat()
        self.asv.pindah(0.0, 0.0)
        self.tick_selama(gf, 30.0)
        self.assertEqual(self.misi.jumlah_abort, 0)

    def test_gps_buruk_memperingatkan_sekali_saja(self):
        gf = self.buat()
        self.asv.pindah(0.0, 0.0)
        self.tick_selama(gf, 30.0)
        kode = [c for _, c, _ in self.peringatan if c == "GEOFENCE_GPS_TIDAK_VALID"]
        self.assertEqual(len(kode), 1, "peringatan tidak boleh membanjiri log")

    def test_gps_pulih_lalu_di_luar_tetap_membatalkan(self):
        gf = self.buat()
        self.asv.pindah(0.0, 0.0)
        self.tick_selama(gf, 5.0)
        self.asv.pindah(geser_utara(LAT, 40), LON)
        self.tick_selama(gf, gf.CONFIRM_SEC + 1.0)
        self.assertEqual(self.misi.jumlah_abort, 1)


class UjiHisteresis(UjiGeofence):
    def test_masuk_tipis_tidak_menghapus_hitungan_pelanggaran(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 40), LON)   # di luar
        gf._tick()
        self.jam.maju(1.0)
        # Kembali ke 1 m DI DALAM sisi — masih di pita histeresis (3 m).
        self.asv.pindah(geser_utara(LAT, 29), LON)
        gf._tick()
        self.assertIsNotNone(gf._melanggar_sejak,
                             "pita histeresis tidak boleh menghapus hitungan")

    def test_masuk_cukup_dalam_menghapus_hitungan_pelanggaran(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 40), LON)
        gf._tick()
        self.jam.maju(1.0)
        # 10 m di dalam sisi — lebih dalam dari HYSTERESIS_M.
        self.asv.pindah(geser_utara(LAT, 20), LON)
        gf._tick()
        self.assertIsNone(gf._melanggar_sejak)

    def test_mengambang_di_garis_batas_akhirnya_tetap_membatalkan(self):
        """
        TEMUAN, bukan cacat — dan perlu diketahui operator.

        Histeresis 3 m hanya mengatur kapan pelanggaran dianggap BERAKHIR, bukan
        kapan ia dimulai. Begitu kapal menyentuh 0 m di luar, hitungan berjalan,
        dan HANYA kembali sedalam 3 m yang menghentikannya. Kapal yang mengambang
        setengah meter keluar-masuk tidak pernah memenuhi syarat itu, jadi setelah
        CONFIRM_SEC misinya dibatalkan.

        Konsekuensinya: galat GPS biasa 1-3 m. Batas yang digambar TEPAT di tempat
        kapal beroperasi bisa membatalkan misi tanpa kapal benar-benar pergi ke
        mana pun. Gambar batasnya dengan kelonggaran.

        Uji ini mengunci perilaku itu supaya perubahan diam-diam ketahuan — bukan
        menyatakan bahwa angkanya sudah pasti benar.
        """
        gf = self.buat()
        for _ in range(20):
            self.asv.pindah(geser_utara(LAT, 30.5), LON)  # tipis di luar
            gf._tick()
            self.jam.maju(0.2)
            self.asv.pindah(geser_utara(LAT, 29.5), LON)  # tipis di dalam
            gf._tick()
            self.jam.maju(0.2)
        self.assertEqual(self.misi.jumlah_abort, 1)

    def test_setelah_dimaafkan_hitungan_mulai_dari_nol_lagi(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 40), LON)   # di luar
        gf._tick()
        self.jam.maju(1.9)                            # hampir cukup lama
        self.asv.pindah(geser_utara(LAT, 20), LON)   # kembali 10 m di dalam
        gf._tick()
        self.asv.pindah(geser_utara(LAT, 40), LON)   # keluar lagi
        gf._tick()
        self.jam.maju(1.0)
        gf._tick()
        # Kalau hitungan lama tidak benar-benar dilupakan, 1,9 + 1,0 detik sudah
        # melewati CONFIRM_SEC dan misi dibatalkan padahal kapal baru saja keluar.
        self.assertEqual(self.misi.jumlah_abort, 0)


class UjiMulaiMisi(UjiGeofence):
    def test_menolak_misi_kalau_kapal_sudah_di_luar(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 100), LON)
        ok, pesan = gf.on_mission_started()
        self.assertFalse(ok)
        self.assertIn("DI LUAR", pesan)

    def test_mengizinkan_misi_kalau_kapal_di_dalam(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 10), LON)
        ok, _ = gf.on_mission_started()
        self.assertTrue(ok)

    def test_pusat_dikunci_ke_posisi_kapal_kalau_belum_ditentukan(self):
        gf = self.buat(pusat=None)
        self.assertIsNone(gf.center)
        self.asv.pindah(LAT, LON)
        ok, _ = gf.on_mission_started()
        self.assertTrue(ok)
        self.assertEqual(gf.center, (LAT, LON))

    def test_gps_belum_valid_tidak_menolak_misi(self):
        # GPS bisa mengunci beberapa detik kemudian; menolak misi karena ini
        # akan membuat geofence terlihat seperti kerusakan.
        gf = self.buat(pusat=None)
        self.asv.pindah(0.0, 0.0)
        ok, _ = gf.on_mission_started()
        self.assertTrue(ok)
        self.assertIsNone(gf.center)

    def test_pusat_menyusul_dikunci_saat_gps_akhirnya_mengunci(self):
        gf = self.buat(pusat=None)
        self.asv.pindah(0.0, 0.0)
        gf.on_mission_started()
        self.asv.pindah(LAT, LON)
        gf._tick()
        self.assertEqual(gf.center, (LAT, LON))

    def test_pelanggaran_lama_dilupakan_saat_misi_baru_mulai(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 40), LON)
        gf._tick()
        self.assertIsNotNone(gf._melanggar_sejak)
        self.asv.pindah(LAT, LON)
        gf.on_mission_started()
        self.assertIsNone(gf._melanggar_sejak)


class UjiConfigure(UjiGeofence):
    def test_mengubah_ukuran_dari_peta(self):
        gf = self.buat()
        gf.configure(lebar_m=200, tinggi_m=150)
        self.assertEqual((gf.lebar_m, gf.tinggi_m), (200.0, 150.0))

    def test_mematikan_tidak_menghapus_ukuran_dan_pusat(self):
        # Operator sering mematikannya sementara saat menguji sesuatu; kehilangan
        # batas yang sudah susah payah digambar setiap kali itu terjadi bukan
        # sesuatu yang bisa dimaafkan di tengah lomba.
        gf = self.buat()
        gf.configure(enabled=False)
        self.assertEqual((gf.lebar_m, gf.tinggi_m), (100.0, 60.0))
        self.assertEqual(gf.center, (LAT, LON))

    def test_menyalakan_kembali_memulihkan_batas_yang_sama(self):
        gf = self.buat()
        gf.configure(enabled=False)
        gf.configure(enabled=True)
        self.assertTrue(gf.enabled)
        self.assertEqual((gf.lebar_m, gf.tinggi_m), (100.0, 60.0))

    def test_field_yang_tidak_dikirim_dibiarkan_apa_adanya(self):
        gf = self.buat()
        gf.configure(lebar_m=200)
        self.assertEqual(gf.tinggi_m, 60.0, "tinggi tidak boleh ikut berubah")
        self.assertEqual(gf.center, (LAT, LON))

    def test_pusat_tidak_masuk_akal_diabaikan(self):
        gf = self.buat()
        gf.configure(lat=0.0, lon=0.0)
        self.assertEqual(gf.center, (LAT, LON), "0,0 tidak boleh menggeser pusat")

    def test_ukuran_negatif_dijepit_ke_nol(self):
        gf = self.buat()
        gf.configure(lebar_m=-50)
        self.assertEqual(gf.lebar_m, 0.0)
        self.assertFalse(gf.enabled)

    def test_ukuran_bukan_angka_diabaikan(self):
        gf = self.buat()
        gf.configure(lebar_m="entah")
        self.assertEqual(gf.lebar_m, 100.0)

    def test_configure_melupakan_pelanggaran_yang_sedang_dihitung(self):
        gf = self.buat()
        self.asv.pindah(geser_utara(LAT, 40), LON)
        gf._tick()
        self.assertIsNotNone(gf._melanggar_sejak)
        gf.configure(tinggi_m=200)   # batas baru = penilaian baru
        self.assertIsNone(gf._melanggar_sejak)


class UjiEnv(UjiGeofence):
    def test_membaca_lebar_dan_tinggi_dari_env(self):
        os.environ["ASV_GEOFENCE_LEBAR_M"] = "120"
        os.environ["ASV_GEOFENCE_TINGGI_M"] = "80"
        gf = GeofenceMonitor(self.asv, mission_engine=self.misi)
        self.assertEqual((gf.lebar_m, gf.tinggi_m), (120.0, 80.0))

    def test_radius_usang_dibaca_sebagai_kotak_dua_kali_lipat(self):
        # Mini PC yang .env-nya masih dari versi lingkaran. Tanpa jalur ini kapal
        # yang sudah terpasang di lapangan boot TANPA geofence sama sekali, dan
        # tidak ada apa pun di layar yang menunjukkan pagarnya hilang.
        os.environ["ASV_GEOFENCE_RADIUS_M"] = "60"
        gf = GeofenceMonitor(self.asv, mission_engine=self.misi)
        self.assertEqual((gf.lebar_m, gf.tinggi_m), (120.0, 120.0))
        self.assertTrue(gf.enabled)

    def test_lebar_baru_menang_atas_radius_usang(self):
        os.environ["ASV_GEOFENCE_LEBAR_M"] = "200"
        os.environ["ASV_GEOFENCE_TINGGI_M"] = "100"
        os.environ["ASV_GEOFENCE_RADIUS_M"] = "60"
        gf = GeofenceMonitor(self.asv, mission_engine=self.misi)
        self.assertEqual((gf.lebar_m, gf.tinggi_m), (200.0, 100.0))

    def test_satu_sisi_saja_menjadi_bujur_sangkar(self):
        os.environ["ASV_GEOFENCE_LEBAR_M"] = "80"
        gf = GeofenceMonitor(self.asv, mission_engine=self.misi)
        self.assertEqual((gf.lebar_m, gf.tinggi_m), (80.0, 80.0))

    def test_env_kosong_berarti_nonaktif(self):
        gf = GeofenceMonitor(self.asv, mission_engine=self.misi)
        self.assertFalse(gf.enabled)

    def test_env_rusak_tidak_melempar(self):
        os.environ["ASV_GEOFENCE_LEBAR_M"] = "seratus"
        gf = GeofenceMonitor(self.asv, mission_engine=self.misi)
        self.assertFalse(gf.enabled)


class UjiDiagonal(UjiGeofence):
    def test_diagonal_untuk_fence_radius_ardupilot(self):
        # FENCE_RADIUS di ArduPilot tetap LINGKARAN. Kalau disetel lebih kecil
        # dari ini, ArduPilot bertindak lebih dulu di dalam kotak yang masih sah.
        gf = self.buat(lebar=80, tinggi=60)
        self.assertAlmostEqual(gf.diagonal_m, 50.0, places=6)  # (80,60,100)/2


if __name__ == "__main__":
    unittest.main(verbosity=2)
