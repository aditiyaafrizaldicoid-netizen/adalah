"""
Uji mutu sinyal GPS yang dikirim ke dashboard.

Jalankan:  python3 tools/uji_gps_fix.py

Sebelum perekam lintasan dibuat, `gps_fix` yang dikirim ke base station dikarang:
`3 if lat else 0`. Artinya dashboard melaporkan "3D fix" selama koordinatnya bukan
nol — padahal koordinat pertama saat penerima masih mencari satelit MEMANG bukan
nol, cuma meleset puluhan meter. Perekam jejak yang mempercayai angka itu akan
menggambar lompatan melintasi danau sebagai lintasan yang sungguh ditempuh.

Yang diuji di sini adalah bahwa angka itu sekarang benar-benar berasal dari
GPS_RAW_INT, dan bahwa posisi yang masih mengalir TIDAK dianggap bukti fix.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connection.parser import MAVLinkParser
from core.state import ASVState


class PesanPalsu:
    """Pesan MAVLink palsu: cukup punya get_type() dan atribut yang dibaca parser."""

    def __init__(self, tipe, **atribut):
        self._tipe = tipe
        for k, v in atribut.items():
            setattr(self, k, v)

    def get_type(self):
        return self._tipe


class UjiMutuGps(unittest.TestCase):

    def setUp(self):
        self.state = ASVState()
        self.parser = MAVLinkParser(self.state)

    def test_gps_raw_int_mengisi_mutu_sinyal(self):
        self.parser.parse_message(PesanPalsu(
            "GPS_RAW_INT", fix_type=3, satellites_visible=11, eph=120))
        d = self.state.to_dict()
        self.assertEqual(d["gps_fix_type"], 3)
        self.assertEqual(d["satellites_visible"], 11)
        self.assertAlmostEqual(d["gps_eph"], 1.2, places=6, msg="eph datang dalam cm")

    def test_eph_tidak_diketahui_jadi_nol(self):
        self.parser.parse_message(PesanPalsu(
            "GPS_RAW_INT", fix_type=2, satellites_visible=5, eph=65535))
        self.assertEqual(self.state.to_dict()["gps_eph"], 0.0,
                         "65535 adalah penanda 'tidak diketahui', bukan HDOP 655 m")

    def test_tanpa_fix_dilaporkan_apa_adanya(self):
        self.parser.parse_message(PesanPalsu(
            "GPS_RAW_INT", fix_type=0, satellites_visible=0, eph=65535))
        self.assertEqual(self.state.to_dict()["gps_fix_type"], 0)

    def test_posisi_yang_mengalir_BUKAN_bukti_fix(self):
        """
        Inti perbaikannya.

        GLOBAL_POSITION_INT tetap mengalir memakai estimasi EKF walau fix sudah
        hilang. Koordinat yang masih masuk sama sekali bukan bukti GPS terkunci —
        justru itulah yang membuat rumus lama `3 if lat else 0` selalu optimis.
        """
        self.state.update_gps(lat=-7.92, lon=112.59, alt=100.0,
                              heading=90.0, ground_speed=1.5)
        d = self.state.to_dict()
        self.assertNotEqual(d["lat"], 0.0, "posisi memang masuk")
        self.assertEqual(d["gps_fix_type"], 0,
                         "tapi tidak boleh menaikkan mutu fix sedikit pun")

    def test_fix_hilang_tidak_membeku_di_nilai_lama(self):
        self.parser.parse_message(PesanPalsu(
            "GPS_RAW_INT", fix_type=3, satellites_visible=12, eph=90))
        self.assertEqual(self.state.to_dict()["gps_fix_type"], 3)
        self.parser.parse_message(PesanPalsu(
            "GPS_RAW_INT", fix_type=1, satellites_visible=2, eph=65535))
        d = self.state.to_dict()
        self.assertEqual(d["gps_fix_type"], 1)
        self.assertEqual(d["satellites_visible"], 2)

    def test_atribut_yang_tidak_ada_tidak_bikin_crash(self):
        """Dialek MAVLink berbeda tidak boleh mematikan thread pembaca."""
        self.parser.parse_message(PesanPalsu("GPS_RAW_INT"))
        self.assertEqual(self.state.to_dict()["gps_fix_type"], 0)

    def test_satelit_terbaca_bukan_lagi_nol_selamanya(self):
        """
        Parser lama tidak pernah mendengarkan GPS_RAW_INT sama sekali, jadi
        jumlah satelit di dashboard selalu 0 apa pun keadaannya.
        """
        self.assertEqual(self.state.to_dict()["satellites_visible"], 0)
        self.parser.parse_message(PesanPalsu(
            "GPS_RAW_INT", fix_type=3, satellites_visible=9, eph=110))
        self.assertEqual(self.state.to_dict()["satellites_visible"], 9)

    def test_gps_raw_int_benar_benar_dirutekan(self):
        """Penjaga: pesan ini pernah tidak ada di daftar parse_message sama sekali."""
        import inspect
        sumber = inspect.getsource(MAVLinkParser.parse_message)
        self.assertIn("GPS_RAW_INT", sumber)


if __name__ == "__main__":
    unittest.main(verbosity=2)
