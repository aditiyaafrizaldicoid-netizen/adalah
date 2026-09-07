"""
Uji penghitung waktu misi: hanya boleh ada SATU yang menghitung.

Jalankan:  python3 tools/uji_timer_misi.py

BUG LAPANGAN: tiap pemanggilan _start_elapsed_timer() langsung membuat thread
baru. Thread LAMA belum tentu sudah keluar — loop-nya baru memeriksa benderanya
setelah sleep(1) selesai — sehingga pause lalu resume dalam waktu kurang dari
satu detik meninggalkan dua thread hidup sekaligus.

Dikonfirmasi sebelum perbaikan: tiga siklus pause/resume → EMPAT thread, dan
8 detik tercatat dalam 2,2 detik nyata. Durasi lomba di dashboard jadi karangan,
dan siaran status ikut berlipat. Tidak ada error di mana pun.
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control.mission_engine import MissionEngine


class Tel:
    mode = "MANUAL"


class AsvPalsu:
    def is_connected(self): return True
    def get_telemetry(self): return Tel()
    def set_mode(self, m): return True
    def stop_movement(self, silent=False): return True


class Ctl:
    def reset(self): pass


class UjiTimerMisi(unittest.TestCase):

    def setUp(self):
        self.e = MissionEngine(AsvPalsu(), None, Ctl(),
                               camera_width=1280, camera_height=720)
        self.e.load_mission([{"type": "TIMED_STEER", "duration_sec": 99},
                             {"type": "FINISH"}])

    def tearDown(self):
        self.e.abort_mission()
        self.e._elapsed_running = False
        time.sleep(1.1)   # beri kesempatan thread keluar sebelum uji berikutnya

    def hidup(self):
        """Jumlah thread penghitung yang masih menjalankan _elapsed_loop."""
        return sum(1 for t in threading.enumerate()
                   if t.is_alive() and getattr(t, "_target", None) is not None
                   and getattr(t._target, "__name__", "") == "_elapsed_loop")

    def test_satu_thread_setelah_start(self):
        self.e.start_mission()
        self.assertEqual(self.hidup(), 1)

    def test_pause_resume_cepat_TIDAK_menambah_thread(self):
        self.e.start_mission()
        self.e.pause_mission()
        self.e.resume_mission()      # dalam < 1 detik
        time.sleep(1.2)              # thread lama sudah punya kesempatan keluar
        self.assertEqual(self.hidup(), 1,
                         "thread lama masih hidup — waktu misi akan berjalan ganda")

    def test_banyak_siklus_tetap_satu(self):
        self.e.start_mission()
        for _ in range(4):
            self.e.pause_mission()
            self.e.resume_mission()
        time.sleep(1.2)
        self.assertEqual(self.hidup(), 1)

    def test_waktu_berjalan_SEWAJARNYA(self):
        """Inti dampaknya: durasi lomba yang dilaporkan harus benar."""
        self.e.start_mission()
        for _ in range(3):
            self.e.pause_mission()
            self.e.resume_mission()
        self.e._elapsed_sec = 0
        awal = time.time()
        time.sleep(2.3)
        nyata = time.time() - awal
        self.assertLessEqual(self.e._elapsed_sec, round(nyata) + 1,
                             f"{self.e._elapsed_sec} detik tercatat dalam "
                             f"{nyata:.1f} detik nyata")

    def test_start_ulang_tidak_menumpuk(self):
        self.e.start_mission()
        self.e.abort_mission()
        self.e.start_mission()
        time.sleep(1.2)
        self.assertEqual(self.hidup(), 1)

    def test_stop_benar_benar_menghentikan(self):
        self.e.start_mission()
        self.e.abort_mission()
        time.sleep(1.2)
        self.assertEqual(self.hidup(), 0, "thread tetap hidup setelah misi dibatalkan")


if __name__ == "__main__":
    unittest.main(verbosity=2)
