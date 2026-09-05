"""
Uji dua langkah docking sederhana: BALL_SEEK dan BALL_STOP.

Jalankan:  python3 tools/uji_ball_steps.py

BALL_SEEK dibatasi WAKTU, BALL_STOP dibatasi UKURAN BOLA. Keduanya sengaja hanya
melakukan satu hal supaya bisa dirangkai dan supaya kalau meleset di danau,
jelas bagian mana yang perlu disetel.

Yang dijaga di sini adalah kegagalan yang tidak menimbulkan error: hitungan waktu
yang diam-diam ter-reset tiap kali deteksi berkedip, dan throttle yang justru naik
saat kapal paling dekat dengan bola.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control.mission_engine import MissionEngine

LEBAR, TINGGI = 1920, 1080
TENGAH = LEBAR / 2


class Tel:
    mode = "MANUAL"


class AsvPalsu:
    def __init__(self):
        self.berhenti = 0

    def is_connected(self): return True
    def get_telemetry(self): return Tel()
    def set_mode(self, m): return True
    def stop_movement(self, silent=False):
        self.berhenti += 1
        return True


class Ctl:
    def reset(self): pass


def bola(cx, sisi=80):
    return (cx, TINGGI / 2, cx - sisi / 2, TINGGI / 2 - sisi / 2,
            cx + sisi / 2, TINGGI / 2 + sisi / 2)


class Basis:
    def setUp(self):
        self.asv = AsvPalsu()
        self.engine = MissionEngine(self.asv, None, Ctl(),
                                    camera_width=LEBAR, camera_height=TINGGI)

    def mulai(self, tipe, **field):
        step = {"type": tipe}
        step.update(field)
        self.engine.load_mission([step, {"type": "FINISH"}])
        self.engine.start_mission()

    def jalankan(self, biru):
        return self.engine.update_frame(
            None, None, {"red": [], "green": [], "blue": biru})

    def idx(self):
        return self.engine.get_status_dict()["current_step_idx"]


class UjiBallSeek(Basis, unittest.TestCase):
    """Fitur 1: cari bola → dekati selama durasi tertentu."""

    def test_tanpa_bola_menyapu_dengan_setelan_cari(self):
        self.mulai("BALL_SEEK", search_throttle=0.35, search_steer=-0.3,
                   approach_throttle=0.9)
        steer, thr, label = self.jalankan([])
        self.assertIn("CARI", label)
        self.assertAlmostEqual(steer, -0.3, places=6)
        self.assertAlmostEqual(thr, 0.35, places=6, msg="harus pakai throttle CARI")

    def test_bola_ketemu_memakai_throttle_mendekat(self):
        self.mulai("BALL_SEEK", search_throttle=0.35, approach_throttle=0.18,
                   approach_sec=5.0)
        steer, thr, label = self.jalankan([bola(TENGAH + 400)])
        self.assertIn("DEKATI", label)
        self.assertAlmostEqual(thr, 0.18, places=6)
        self.assertGreater(steer, 0.0, "bola di kanan → kemudi ke kanan")

    def test_kemudi_mengarah_ke_bola(self):
        self.mulai("BALL_SEEK", approach_sec=5.0)
        steer, _, _ = self.jalankan([bola(TENGAH - 400)])
        self.assertLess(steer, 0.0, "bola di kiri → kemudi ke kiri")

    def test_batas_kemudi_dihormati(self):
        self.mulai("BALL_SEEK", approach_sec=5.0, steer_gain=10.0, max_steer=0.25)
        steer, _, _ = self.jalankan([bola(TENGAH + 900)])
        self.assertLessEqual(abs(steer), 0.25 + 1e-9)

    def test_selesai_setelah_durasi_mendekat(self):
        self.mulai("BALL_SEEK", approach_sec=0.25)
        self.jalankan([bola(TENGAH)])
        self.assertEqual(self.idx(), 0)
        time.sleep(0.3)
        steer, thr, _ = self.jalankan([bola(TENGAH)])
        self.assertEqual((steer, thr), (0.0, 0.0))
        self.assertGreater(self.idx(), 0)

    def test_waktu_mendekat_DIAKUMULASI_lintas_kedipan(self):
        """
        Kalau hitungannya ter-reset tiap bola berkedip, "dekati 4 detik" berubah
        jadi mendekat berkali-kali selama durasi penuh — jauh lebih lama dari
        yang diminta, dan kapal melewati sasarannya.
        """
        self.mulai("BALL_SEEK", approach_sec=0.4, lost_grace_sec=0.0)
        self.jalankan([bola(TENGAH)])
        time.sleep(0.25)
        self.jalankan([])                 # bola hilang → kembali mencari
        self.jalankan([bola(TENGAH)])     # ketemu lagi
        time.sleep(0.25)                  # total mendekat ≈ 0.5s > 0.4s
        self.jalankan([bola(TENGAH)])
        self.assertGreater(self.idx(), 0, "hitungan waktu ter-reset saat bola berkedip")

    def test_kedip_sesaat_menahan_kemudi(self):
        self.mulai("BALL_SEEK", approach_sec=9.0, lost_grace_sec=5.0)
        steer_awal, _, _ = self.jalankan([bola(TENGAH + 400)])
        steer_hilang, _, label = self.jalankan([])
        self.assertAlmostEqual(steer_hilang, steer_awal, places=6)
        self.assertIn("hilang sekejap", label)

    def test_tidak_ketemu_step_diselesaikan(self):
        self.mulai("BALL_SEEK", search_timeout_sec=0.2)
        self.jalankan([])
        time.sleep(0.25)
        self.jalankan([])
        self.assertGreater(self.idx(), 0, "kapal tidak boleh menyapu tanpa batas")

    def test_bola_terlalu_kecil_diabaikan(self):
        self.mulai("BALL_SEEK", min_detect_area_px2=20000, approach_sec=5.0)
        _, _, label = self.jalankan([bola(TENGAH, sisi=40)])
        self.assertIn("CARI", label)


class UjiBallStop(Basis, unittest.TestCase):
    """Fitur 2: dekati → berhenti saat ukuran bola mencapai ambang."""

    def test_masih_kecil_terus_mendekat(self):
        self.mulai("BALL_STOP", stop_area_px2=100000, approach_throttle=0.2)
        _, thr, label = self.jalankan([bola(TENGAH, sisi=100)])
        self.assertIn("DEKATI", label)
        self.assertAlmostEqual(thr, 0.2, places=6)

    def test_ukuran_tercapai_maka_BERHENTI_TOTAL(self):
        self.mulai("BALL_STOP", stop_area_px2=10000, approach_throttle=0.2,
                   hold_sec=5.0)
        steer, thr, label = self.jalankan([bola(TENGAH, sisi=200)])
        self.assertIn("BERHENTI", label)
        self.assertEqual(thr, 0.0, "throttle harus diputus")
        self.assertEqual(steer, 0.0)
        self.assertGreater(self.asv.berhenti, 0, "perintah berhenti harus dikirim tegas")

    def test_ambang_menentukan_JARAK_berhenti(self):
        """Ambang lebih besar = bola harus terlihat lebih besar = kapal lebih dekat."""
        self.mulai("BALL_STOP", stop_area_px2=40000, hold_sec=5.0)
        _, _, label = self.jalankan([bola(TENGAH, sisi=150)])   # 22.500 px²
        self.assertIn("DEKATI", label, "belum cukup besar, jangan berhenti dulu")
        _, _, label = self.jalankan([bola(TENGAH, sisi=220)])   # 48.400 px²
        self.assertIn("BERHENTI", label)

    def test_throttle_berhenti_dijepit_ke_throttle_mendekat(self):
        """Kapal tidak boleh menambah gas justru saat paling dekat dengan bola."""
        self.mulai("BALL_STOP", stop_area_px2=10000, approach_throttle=0.2,
                   stop_throttle=0.9, hold_sec=5.0)
        _, thr, _ = self.jalankan([bola(TENGAH, sisi=200)])
        self.assertLessEqual(thr, 0.2)

    def test_dorongan_kecil_tetap_boleh(self):
        self.mulai("BALL_STOP", stop_area_px2=10000, approach_throttle=0.2,
                   stop_throttle=0.05, hold_sec=5.0)
        _, thr, _ = self.jalankan([bola(TENGAH, sisi=200)])
        self.assertAlmostEqual(thr, 0.05, places=6)

    def test_selesai_setelah_menahan(self):
        self.mulai("BALL_STOP", stop_area_px2=10000, hold_sec=0.2)
        self.jalankan([bola(TENGAH, sisi=200)])
        time.sleep(0.25)
        self.jalankan([])
        self.assertGreater(self.idx(), 0)

    def test_bola_hilang_di_jarak_dekat_BERHENTI_bukan_maju_buta(self):
        """Di jarak dekat bola keluar frame atau tenggelam di bawah haluan."""
        self.mulai("BALL_STOP", stop_area_px2=999999, lost_grace_sec=0.15,
                   hold_sec=5.0)
        self.jalankan([bola(TENGAH, sisi=200)])
        time.sleep(0.2)
        steer, thr, label = self.jalankan([])
        self.assertIn("BERHENTI", label)
        self.assertEqual(thr, 0.0)

    def test_fase_berhenti_tidak_dibatalkan_deteksi_berkedip(self):
        self.mulai("BALL_STOP", stop_area_px2=10000, hold_sec=5.0)
        self.jalankan([bola(TENGAH, sisi=200)])
        _, _, label = self.jalankan([])
        self.assertIn("BERHENTI", label)

    def test_tanpa_bola_sama_sekali_mencari_lalu_menyerah(self):
        self.mulai("BALL_STOP", search_timeout_sec=0.2, search_throttle=0.3)
        _, thr, label = self.jalankan([])
        self.assertIn("CARI", label)
        self.assertAlmostEqual(thr, 0.3, places=6)
        time.sleep(0.25)
        self.jalankan([])
        self.assertGreater(self.idx(), 0)


class UjiPengamanUmum(Basis, unittest.TestCase):

    def test_batas_keras_kedua_step(self):
        for tipe in ("BALL_SEEK", "BALL_STOP"):
            with self.subTest(tipe=tipe):
                self.setUp()
                self.mulai(tipe, max_duration_sec=0.3, approach_sec=999,
                           stop_area_px2=999999, search_timeout_sec=999)
                for _ in range(3):
                    self.jalankan([bola(TENGAH)])
                time.sleep(0.35)
                self.jalankan([bola(TENGAH)])
                self.assertGreater(self.idx(), 0)

    def test_field_kosong_tidak_bikin_crash(self):
        for tipe in ("BALL_SEEK", "BALL_STOP"):
            with self.subTest(tipe=tipe):
                self.setUp()
                self.mulai(tipe, search_throttle="", search_steer="",
                           approach_throttle=None, approach_sec="abc",
                           stop_area_px2="", stop_throttle="", steer_gain="",
                           max_steer="", hold_sec="")
                for biru in ([], [bola(TENGAH)], [bola(TENGAH, sisi=300)], []):
                    steer, thr, _ = self.jalankan(biru)
                    self.assertTrue(-1.0 <= steer <= 1.0, f"steer {steer}")
                    self.assertTrue(0.0 <= thr <= 1.0, f"throttle {thr}")

    def test_keluaran_selalu_dalam_batas_aman(self):
        for tipe in ("BALL_SEEK", "BALL_STOP"):
            with self.subTest(tipe=tipe):
                self.setUp()
                self.mulai(tipe, search_throttle=9, search_steer=-9,
                           approach_throttle=9, steer_gain=99, max_steer=9,
                           stop_throttle=9, approach_sec=9, hold_sec=9,
                           stop_area_px2=10000)
                for biru in ([], [bola(50)], [bola(TENGAH, sisi=400)], []):
                    steer, thr, _ = self.jalankan(biru)
                    self.assertTrue(-1.0 <= steer <= 1.0, f"steer {steer}")
                    self.assertTrue(0.0 <= thr <= 1.0, f"throttle {thr}")

    def test_dua_step_bisa_dirangkai(self):
        """BALL_SEEK lalu BALL_STOP: kasar dulu dengan waktu, halus dengan jarak."""
        self.engine.load_mission([
            {"type": "BALL_SEEK", "approach_sec": 0.2},
            {"type": "BALL_STOP", "stop_area_px2": 10000, "hold_sec": 0.2},
            {"type": "FINISH"},
        ])
        self.engine.start_mission()
        self.jalankan([bola(TENGAH, sisi=100)])
        time.sleep(0.25)
        self.jalankan([bola(TENGAH, sisi=100)])
        self.assertEqual(self.idx(), 1, "harus lanjut ke BALL_STOP")
        _, _, label = self.jalankan([bola(TENGAH, sisi=200)])
        self.assertIn("BALL_STOP", label)


if __name__ == "__main__":
    unittest.main(verbosity=2)
