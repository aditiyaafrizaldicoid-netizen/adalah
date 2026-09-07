"""
Uji bahwa permintaan foto tidak bocor melewati batas step maupun misi.

Jalankan:  python3 tools/uji_kebocoran_shutter.py

BUG LAPANGAN: step yang memotret menyalakan _capture_pending lalu MENUNGGU
main.py menyerahkan frame kamera yang bersih. Kalau step itu berakhir sebelum
frame tersebut datang — misi dibatalkan, remote mengambil alih, geofence
memutus, atau batas waktu habis — benderanya tetap menyala dan terbawa ke step
berikutnya, bahkan ke MISI berikutnya.

Frame pertama yang masuk lalu disimpan sebagai foto memakai label target lama.
Dikonfirmasi sebelum perbaikan: membatalkan TAKE_IMAGE lalu menjalankan misi
yang sama sekali tidak punya step foto tetap menghasilkan '..._dermaga.jpg'
di dashboard — bukti misi yang tidak pernah terjadi, tanpa satu pun error.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from control.mission_engine import MissionEngine


class Tel:
    mode = "MANUAL"


class AsvPalsu:
    def is_connected(self): return True
    def get_telemetry(self): return Tel()
    def get_telemetry_dict(self): return {"lat": -7.9, "lon": 112.6, "heading": 90.0}
    def set_mode(self, m): return True
    def stop_movement(self, silent=False): return True
    def release_rc(self, *a, **k): return True


class Ctl:
    def reset(self): pass


FRAME = np.full((80, 100, 3), 120, dtype=np.uint8)


class UjiKebocoranShutter(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="uji_shutter_")
        self.e = MissionEngine(AsvPalsu(), None, Ctl(),
                               camera_width=1280, camera_height=720)
        self.e.CAPTURE_DIR = self.dir

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def frame(self):
        return self.e.update_frame(None, None, {"red": [], "green": [], "blue": []})

    def minta_shutter(self):
        """Jalankan TAKE_IMAGE sampai ia meminta shutter, tanpa melayaninya."""
        self.e.load_mission([{"type": "TAKE_IMAGE", "name": "dermaga"},
                             {"type": "FINISH"}])
        self.e.start_mission()
        self.frame()
        self.assertTrue(self.e.capture_pending, "TAKE_IMAGE belum meminta shutter")

    # ── Batas MISI ────────────────────────────────────────────────────────

    def test_batal_misi_memadamkan_permintaan(self):
        self.minta_shutter()
        self.e.abort_mission()
        self.assertFalse(self.e.capture_pending)

    def test_reset_misi_memadamkan_permintaan(self):
        self.minta_shutter()
        self.e.reset_mission()
        self.assertFalse(self.e.capture_pending)

    def test_misi_baru_tidak_mewarisi_permintaan(self):
        """Inti bugnya: misi tanpa step foto tetap menghasilkan foto."""
        self.minta_shutter()
        self.e.abort_mission()
        self.e.load_mission([{"type": "TIMED_STEER", "duration_sec": 5},
                             {"type": "FINISH"}])
        self.e.start_mission()
        self.assertFalse(self.e.capture_pending,
                         "misi baru mewarisi permintaan foto misi sebelumnya")
        self.assertIsNone(self.e.capture_now(FRAME))
        self.assertEqual(os.listdir(self.dir), [],
                         "foto tersimpan padahal misi ini tidak punya step foto")

    def test_label_lama_ikut_dibersihkan(self):
        """Label yang tertinggal akan menamai foto berikutnya dengan target salah."""
        self.minta_shutter()
        self.assertEqual(self.e._capture_label, "dermaga")
        self.e.abort_mission()
        self.assertEqual(self.e._capture_label, "")

    # ── Batas STEP ────────────────────────────────────────────────────────

    def test_step_berikutnya_tidak_mewarisi_permintaan(self):
        """
        TAKE_IMAGE meminta shutter lalu step-nya kedaluwarsa. Step berikutnya
        tidak boleh memotret di momen yang tidak diminta siapa pun.
        """
        self.e.load_mission([
            {"type": "TAKE_IMAGE", "name": "dermaga", "duration_sec": 0.01},
            {"type": "TIMED_STEER", "duration_sec": 5},
            {"type": "FINISH"},
        ])
        self.e.start_mission()
        self.frame()
        self.assertTrue(self.e.capture_pending)

        import time
        time.sleep(0.05)
        for _ in range(3):
            self.frame()

        self.assertGreater(self.e.get_status_dict()["current_step_idx"], 0,
                           "step belum berpindah, uji tidak menguji apa pun")
        self.assertFalse(self.e.capture_pending,
                         "permintaan foto terbawa ke step berikutnya")

    def test_shutter_yang_SAH_tetap_jalan(self):
        """Perbaikan tidak boleh mematikan pemotretan yang memang diminta."""
        self.minta_shutter()
        path = self.e.capture_now(FRAME)
        self.assertIsNotNone(path, "foto yang sah ikut terbatalkan")
        self.assertIn("dermaga", os.path.basename(path))

    def test_pembatalan_berulang_aman(self):
        self.e._batalkan_permintaan_foto()
        self.e._batalkan_permintaan_foto("dua kali")
        self.assertFalse(self.e.capture_pending)


if __name__ == "__main__":
    unittest.main(verbosity=2)
