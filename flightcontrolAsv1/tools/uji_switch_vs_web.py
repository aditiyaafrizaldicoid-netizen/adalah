"""
Uji siapa yang menang antara switch fisik di remote dan tombol di dashboard.

Jalankan:  python3 tools/uji_switch_vs_web.py

BUG LAPANGAN: switch fisik dulu menegaskan posisinya SETIAP putaran (10x per
detik). Akibatnya perubahan sumber kendali dari dashboard hanya bertahan sekitar
100 ms sebelum ditarik balik — tombolnya terlihat rusak padahal perintahnya sampai
di kapal dan dijalankan dengan benar.

Aturan sekarang: switch menang saat DIGERAKKAN. Di antara perpindahan, dashboard
boleh menentukan. Keselamatannya tidak berkurang — operator yang memegang remote
cukup menggerakkan switch untuk merebut kembali kendali seketika.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control import manual_source
from control.rc_source_switch import RCSourceSwitch


class StatePalsu:
    def __init__(self, pwm=1900):
        self.pwm = pwm
        self.segar = True

    def rc_link_fresh(self, _):
        return self.segar

    def get_rc_channel(self, _ch):
        return self.pwm


class AsvPalsu:
    """Cukup menyimpan sumber kendali; tanpa MAVLink."""

    def __init__(self):
        self.state = StatePalsu()
        self._sumber = manual_source.MINIPC
        self.riwayat = []

    def get_manual_source(self):
        return self._sumber

    def set_manual_source(self, s):
        t = manual_source.normalize(s)
        if t is None:
            return False
        self._sumber = t
        self.riwayat.append(t)
        return True


def saklar(asv, invert=False):
    sw = RCSourceSwitch.__new__(RCSourceSwitch)
    sw.asv = asv
    sw.channel = 8
    sw.invert = invert
    sw._is_running = False
    sw._posisi_kandidat = None
    sw._posisi_stabil = None
    sw._kandidat_sejak = 0.0
    sw._link_hidup = None
    sw._on_change = None
    sw._warn = lambda *a, **k: None
    sw.CONFIRM_SEC = 0.0          # debounce dilewati; diuji terpisah
    return sw


class UjiSwitchVsWeb(unittest.TestCase):

    def setUp(self):
        self.asv = AsvPalsu()
        self.sw = saklar(self.asv)

    def tick(self, n=2):
        """
        Default 2 putaran: debounce butuh satu pembacaan untuk MENCATAT posisi
        kandidat dan satu lagi untuk MENGONFIRMASI-nya. Satu putaran saja tidak
        pernah menindaklanjuti apa pun — itu memang perilaku yang benar.
        """
        for _ in range(n):
            self.sw._tick()

    # ── Perilaku dasar switch ─────────────────────────────────────────────

    def test_pembacaan_pertama_menyamakan_dengan_switch(self):
        """Saat boot, kapal harus mengikuti posisi switch yang sebenarnya."""
        self.asv.state.pwm = 1900          # PWM tinggi = REMOTE
        self.tick()
        self.assertEqual(self.asv.get_manual_source(), manual_source.REMOTE)

    def test_switch_digerakkan_merebut_kendali(self):
        self.asv.state.pwm = 1900
        self.tick()
        self.asv.state.pwm = 1100          # digerakkan ke MINIPC
        self.tick()
        self.assertEqual(self.asv.get_manual_source(), manual_source.MINIPC)

    def test_zona_mati_tidak_mengubah_apa_pun(self):
        self.asv.state.pwm = 1900
        self.tick()
        self.asv.state.pwm = 1500          # di antara 1300-1700
        self.tick(5)
        self.assertEqual(self.asv.get_manual_source(), manual_source.REMOTE)

    # ── Inti perbaikan ────────────────────────────────────────────────────

    def test_perubahan_dari_WEB_bertahan(self):
        """
        Switch DIAM di REMOTE, operator memindah ke Mini PC dari dashboard.
        Dulu ini ditarik balik dalam ~100 ms.
        """
        self.asv.state.pwm = 1900
        self.tick()
        self.assertEqual(self.asv.get_manual_source(), manual_source.REMOTE)

        self.asv.set_manual_source("minipc")      # dari dashboard
        self.tick(30)                             # 3 detik berlalu
        self.assertEqual(self.asv.get_manual_source(), manual_source.MINIPC,
                         "switch menarik balik perubahan dari web")

    def test_perubahan_web_ke_arah_sebaliknya_juga_bertahan(self):
        self.asv.state.pwm = 1100                 # switch di MINIPC
        self.tick()
        self.asv.set_manual_source("remote")      # dari dashboard
        self.tick(30)
        self.assertEqual(self.asv.get_manual_source(), manual_source.REMOTE)

    def test_switch_TETAP_bisa_merebut_setelah_diubah_dari_web(self):
        """Keselamatan: operator yang memegang remote harus selalu bisa mengambil alih."""
        self.asv.state.pwm = 1900
        self.tick()
        self.asv.set_manual_source("minipc")      # web mengambil alih
        self.tick(10)
        self.assertEqual(self.asv.get_manual_source(), manual_source.MINIPC)

        self.asv.state.pwm = 1100                 # operator MENGGERAKKAN switch
        self.tick()
        self.assertEqual(self.asv.get_manual_source(), manual_source.MINIPC)
        self.asv.state.pwm = 1900                 # gerakkan lagi ke REMOTE
        self.tick()
        self.assertEqual(self.asv.get_manual_source(), manual_source.REMOTE,
                         "switch harus selalu bisa merebut kembali")

    def test_switch_tidak_memanggil_set_berulang_ulang(self):
        """
        Dulu set_manual_source dipanggil tiap putaran selama berbeda. Tiap
        panggilan mengganti mode FC dan mengirim pelepasan override berulang —
        pekerjaan berat 10x per detik.
        """
        self.asv.state.pwm = 1900
        self.tick(50)
        self.assertEqual(len(self.asv.riwayat), 1,
                         f"set_manual_source dipanggil {len(self.asv.riwayat)}x")

    # ── Sinyal RC ─────────────────────────────────────────────────────────

    def test_sinyal_hilang_tidak_mengubah_sumber(self):
        self.asv.state.pwm = 1900
        self.tick()
        self.asv.set_manual_source("minipc")
        self.asv.state.segar = False
        self.tick(10)
        self.assertEqual(self.asv.get_manual_source(), manual_source.MINIPC,
                         "sinyal hilang bukan alasan memindahkan kendali")

    def test_posisi_switch_dilaporkan_untuk_dashboard(self):
        self.asv.state.pwm = 1900
        self.tick()
        self.assertEqual(self.sw.posisi_switch(), manual_source.REMOTE)
        self.asv.state.segar = False
        self.tick()
        self.assertIsNone(self.sw.posisi_switch(),
                          "sinyal hilang → posisi tidak diketahui, jangan mengarang")

    def test_beda_antara_posisi_switch_dan_sumber_aktif_bisa_dilihat(self):
        """Selisih ini sah sekarang, dan dashboard perlu bisa menampilkannya."""
        self.asv.state.pwm = 1900
        self.tick()
        self.asv.set_manual_source("minipc")
        self.tick(5)
        self.assertEqual(self.sw.posisi_switch(), manual_source.REMOTE)
        self.assertEqual(self.asv.get_manual_source(), manual_source.MINIPC)


if __name__ == "__main__":
    unittest.main(verbosity=2)
