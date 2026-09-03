"""
Uji manuver DOCKING tanpa kapal, kamera, atau flight controller.

Jalankan:  python3 tools/uji_docking.py

Toleransi melenceng manuver ini cuma 5 cm (setengah lambung 20 cm dikurangi
setengah jarak antar bola 15 cm). Karena itu yang diuji di sini bukan "apakah
kapal bergerak" melainkan hal-hal yang salahnya menggeser haluan JAUH melebihi
5 cm dan tidak menimbulkan error apa pun:

  - sisi yang dikunci tidak pernah berubah di tengah pendekatan;
  - bola tengah yang hilang tidak membuat kapal membidik ke bola tengah itu
    sendiri (dan cuma mengenai satu bola);
  - penguncian tidak terjadi selagi baru dua bola terlihat, karena
    (kiri,tengah) dan (tengah,kanan) terlihat identik.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control.mission_engine import MissionEngine

LEBAR, TINGGI = 1920, 1080
TENGAH_FRAME = LEBAR / 2


class AsvPalsu:
    class _Telemetry:
        mode = "MANUAL"

    def is_connected(self):
        return True

    def get_telemetry(self):
        return self._Telemetry()

    def set_mode(self, mode):
        return True

    def stop_movement(self, silent=False):
        return True


class KontrolerPalsu:
    def reset(self):
        pass


def bola(cx, sisi=60):
    """Deteksi (cx, cy, x1, y1, x2, y2) berukuran `sisi` piksel."""
    return (cx, TINGGI / 2, cx - sisi / 2, TINGGI / 2 - sisi / 2,
            cx + sisi / 2, TINGGI / 2 + sisi / 2)


def tiga_bola(pusat=TENGAH_FRAME, jarak=200, sisi=60):
    """Kiri, tengah, kanan — berjajar dengan jarak sama, meniru arena."""
    return [bola(pusat - jarak, sisi), bola(pusat, sisi), bola(pusat + jarak, sisi)]


class UjiDocking(unittest.TestCase):

    def setUp(self):
        self.engine = MissionEngine(AsvPalsu(), None, KontrolerPalsu(),
                                    camera_width=LEBAR, camera_height=TINGGI)

    def mulai(self, **field):
        step = {"type": "DOCKING"}
        step.update(field)
        self.engine.load_mission([step, {"type": "FINISH"}])
        self.engine.start_mission()
        return step

    def jalankan(self, biru):
        return self.engine.update_frame(None, None, {"red": [], "green": [], "blue": biru})

    def kunci(self, biru=None, **field):
        """Jalankan sampai sisi sasaran terkunci."""
        field.setdefault("lock_confirm_sec", 0)
        field.setdefault("ram_area_px2", 10_000_000)   # jangan masuk RAM dulu
        self.mulai(**field)
        self.jalankan(biru if biru is not None else tiga_bola())
        return self.engine._dock_pilihan

    # ── Penguncian sasaran ─────────────────────────────────────────────────

    def test_tidak_mengunci_dengan_dua_bola(self):
        """
        (kiri,tengah) dan (tengah,kanan) terlihat identik kalau cuma dua yang
        tampak. Mengunci di sini = menebak sisi, dan sisi yang salah tidak bisa
        dibatalkan.
        """
        self.mulai(lock_confirm_sec=0)
        _, _, label = self.jalankan([bola(800), bola(1000)])
        self.assertIsNone(self.engine._dock_pilihan)
        self.assertIn("ACQUIRE 2/3", label)

    def test_penguncian_menunggu_konfirmasi(self):
        self.mulai(lock_confirm_sec=0.3, ram_area_px2=10_000_000)
        self.jalankan(tiga_bola())
        self.assertIsNone(self.engine._dock_pilihan, "satu frame belum boleh mengunci")
        time.sleep(0.35)
        self.jalankan(tiga_bola())
        self.assertIsNotNone(self.engine._dock_pilihan)

    def test_auto_memilih_sisi_dengan_haluan_terdekat(self):
        # Kelompok bola condong ke KANAN frame → titik tengah TENGAH+KANAN lebih
        # jauh dari haluan, jadi KIRI+TENGAH yang dipilih.
        self.assertEqual(self.kunci(tiga_bola(pusat=TENGAH_FRAME + 150)), "left")
        self.setUp()
        self.assertEqual(self.kunci(tiga_bola(pusat=TENGAH_FRAME - 150)), "right")

    def test_operator_bisa_memaksa_sisi(self):
        for minta, harap in (("kiri", "left"), ("left", "left"),
                             ("kanan", "right"), ("right", "right")):
            with self.subTest(minta=minta):
                self.setUp()
                # Kelompok condong sehingga "auto" akan memilih sebaliknya.
                sisi = self.kunci(tiga_bola(pusat=TENGAH_FRAME + 150), prefer=minta)
                self.assertEqual(sisi, harap)

    def test_titik_bidik_berada_di_antara_dua_bola_sasaran(self):
        self.kunci(tiga_bola(pusat=TENGAH_FRAME, jarak=200), prefer="kiri")
        # kiri=760, tengah=960 → bidik 860
        self.assertAlmostEqual(self.engine._dock_bidik_px, 860.0, places=3)
        self.setUp()
        self.kunci(tiga_bola(pusat=TENGAH_FRAME, jarak=200), prefer="kanan")
        self.assertAlmostEqual(self.engine._dock_bidik_px, 1060.0, places=3)

    def test_sisi_terkunci_tidak_berubah_walau_kapal_bergeser(self):
        """Berpindah pasangan di tengah jalan menggeser haluan 30 cm — 6x toleransi."""
        self.kunci(tiga_bola(pusat=TENGAH_FRAME + 150), prefer=None)
        awal = self.engine._dock_pilihan
        for geser in (+400, -400, +600, 0):
            self.jalankan(tiga_bola(pusat=TENGAH_FRAME + geser))
            self.assertEqual(self.engine._dock_pilihan, awal,
                             "sisi sasaran berubah setelah dikunci")

    # ── Jebakan bola tengah hilang ─────────────────────────────────────────

    def test_bola_tengah_hilang_tidak_membuat_kapal_membidik_bola_tengah(self):
        """
        Jebakan geometri utama. Kalau bola TENGAH tidak terdeteksi, titik tengah
        antara bola luar menunjuk TEPAT ke posisi bola tengah. Membidik ke sana
        membuat lambung menutup ±20 cm sementara bola luar ada di ±30 cm — cuma
        SATU bola yang kena.
        """
        self.kunci(tiga_bola(pusat=TENGAH_FRAME, jarak=200), prefer="kiri")
        bidik_bertiga = self.engine._dock_bidik_px      # 860

        # Sekarang bola tengah hilang: tinggal kiri(760) & kanan(1160).
        self.jalankan([bola(760), bola(1160)])
        bidik_berdua = self.engine._dock_bidik_px

        self.assertNotAlmostEqual(bidik_berdua, 960.0, places=0,
                                  msg="membidik posisi bola tengah = cuma 1 bola kena")
        self.assertAlmostEqual(bidik_berdua, bidik_bertiga, delta=1.0,
                               msg="bidikan harus tetap di antara kiri & tengah")

    def test_pasangan_luar_juga_benar_untuk_sisi_kanan(self):
        self.kunci(tiga_bola(pusat=TENGAH_FRAME, jarak=200), prefer="kanan")
        self.jalankan([bola(760), bola(1160)])
        self.assertAlmostEqual(self.engine._dock_bidik_px, 1060.0, delta=1.0)

    def test_pasangan_bersebelahan_dipakai_apa_adanya(self):
        self.kunci(tiga_bola(pusat=TENGAH_FRAME, jarak=200), prefer="kiri")
        self.jalankan([bola(760), bola(960)])
        self.assertAlmostEqual(self.engine._dock_bidik_px, 860.0, delta=1.0)

    # ── Kemudi ─────────────────────────────────────────────────────────────

    def test_kemudi_mengarah_ke_titik_bidik(self):
        # Bidikan di KANAN haluan → kemudi positif.
        self.kunci(tiga_bola(pusat=TENGAH_FRAME + 300), prefer="kanan")
        steer, _, _ = self.jalankan(tiga_bola(pusat=TENGAH_FRAME + 300))
        self.assertGreater(steer, 0.0)

        self.setUp()
        self.kunci(tiga_bola(pusat=TENGAH_FRAME - 300), prefer="kiri")
        steer, _, _ = self.jalankan(tiga_bola(pusat=TENGAH_FRAME - 300))
        self.assertLess(steer, 0.0)

    def test_batas_kemudi_dihormati(self):
        self.kunci(tiga_bola(pusat=TENGAH_FRAME + 800), prefer="kanan",
                   steer_gain=10.0, max_steer=0.25)
        steer, _, _ = self.jalankan(tiga_bola(pusat=TENGAH_FRAME + 800))
        self.assertLessEqual(abs(steer), 0.25 + 1e-9)

    # ── Fase RAM ───────────────────────────────────────────────────────────

    def test_dekat_dan_lurus_menabrak_lurus(self):
        self.mulai(lock_confirm_sec=0, prefer="kiri", ram_area_px2=1000,
                   align_tolerance_px=500, ram_sec=5.0)
        steer, _, label = self.jalankan(tiga_bola(pusat=TENGAH_FRAME + 200, sisi=200))
        self.assertIn("RAM", label)
        self.assertEqual(steer, 0.0, "sudah lurus: koreksi sisa justru menggoyang buritan")

    def test_dekat_tapi_belum_lurus_menabrak_dengan_kemudi_terakhir(self):
        self.mulai(lock_confirm_sec=0, prefer="kiri", ram_area_px2=1000,
                   align_tolerance_px=5, ram_sec=5.0)
        steer, _, label = self.jalankan(tiga_bola(pusat=TENGAH_FRAME + 400, sisi=200))
        self.assertIn("RAM", label)
        self.assertNotEqual(steer, 0.0, "belum lurus: koreksi harus dipertahankan")

    def test_bola_hilang_lama_setelah_dikunci_tetap_menabrak(self):
        """Di jarak dekat bola memang tenggelam di bawah haluan."""
        self.kunci(prefer="kiri", lost_grace_sec=0.1, ram_sec=5.0)
        time.sleep(0.15)
        _, _, label = self.jalankan([])
        self.assertIn("RAM", label)

    def test_kedip_deteksi_menahan_kemudi_bukan_meluruskan(self):
        self.kunci(tiga_bola(pusat=TENGAH_FRAME + 300), prefer="kanan",
                   lost_grace_sec=5.0)
        steer_awal, _, _ = self.jalankan(tiga_bola(pusat=TENGAH_FRAME + 300))
        steer_hilang, _, label = self.jalankan([])
        self.assertAlmostEqual(steer_hilang, steer_awal, places=6)
        self.assertIn("hilang sekejap", label)

    def test_step_selesai_setelah_ram(self):
        self.mulai(lock_confirm_sec=0, prefer="kiri", ram_area_px2=1000, ram_sec=0.2)
        self.jalankan(tiga_bola(sisi=200))
        time.sleep(0.25)
        steer, thr, _ = self.jalankan([])
        self.assertEqual((steer, thr), (0.0, 0.0))
        self.assertGreater(self.engine.get_status_dict()["current_step_idx"], 0)

    # ── Pengaman ───────────────────────────────────────────────────────────

    def test_tidak_ketemu_step_diselesaikan(self):
        self.mulai(search_timeout_sec=0.2)
        self.jalankan([])
        time.sleep(0.25)
        self.jalankan([])
        self.assertGreater(self.engine.get_status_dict()["current_step_idx"], 0)

    def test_batas_keras_seluruh_step(self):
        self.mulai(lock_confirm_sec=999, max_duration_sec=0.3)
        for _ in range(3):
            self.jalankan(tiga_bola())
        time.sleep(0.35)
        self.jalankan(tiga_bola())
        self.assertGreater(self.engine.get_status_dict()["current_step_idx"], 0)

    def test_deteksi_palsu_keempat_dibuang(self):
        """Arena cuma punya tiga bola; sisanya pasti pantulan. Ambil tiga terbesar."""
        palsu = bola(1700, 20)
        self.kunci(tiga_bola(jarak=200) + [palsu], prefer="kiri")
        self.assertAlmostEqual(self.engine._dock_bidik_px, 860.0, delta=1.0)

    def test_bola_terlalu_kecil_diabaikan(self):
        self.mulai(min_detect_area_px2=10000, lock_confirm_sec=0)
        _, _, label = self.jalankan(tiga_bola(sisi=40))
        self.assertIn("SEARCH", label)

    def test_field_kosong_tidak_bikin_crash(self):
        self.mulai(search_throttle="", search_steer="", approach_throttle=None,
                   steer_gain="", max_steer="", ram_area_px2="", ram_sec="abc",
                   lock_confirm_sec="", prefer="", ball_spacing_m="")
        for biru in ([], tiga_bola(), [bola(900)], tiga_bola(sisi=250), []):
            steer, thr, _ = self.jalankan(biru)
            self.assertTrue(-1.0 <= steer <= 1.0, f"steer di luar batas: {steer}")
            self.assertTrue(0.0 <= thr <= 1.0, f"throttle di luar batas: {thr}")

    def test_keluaran_selalu_dalam_batas_aman(self):
        self.mulai(search_throttle=9, search_steer=-9, approach_throttle=9,
                   steer_gain=99, max_steer=9, ram_throttle=9, ram_sec=5,
                   lock_confirm_sec=0, ram_area_px2=1000)
        for biru in ([], tiga_bola(pusat=100), tiga_bola(sisi=300), []):
            steer, thr, _ = self.jalankan(biru)
            self.assertTrue(-1.0 <= steer <= 1.0, f"steer di luar batas: {steer}")
            self.assertTrue(0.0 <= thr <= 1.0, f"throttle di luar batas: {thr}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
