"""
Uji bahwa kelas BARU (bola biru) masuk ke sistem TANPA menyentuh kemudi.

Jalankan:  python3 tools/uji_kelas_bola_biru.py

Model per 3 September 2026 menambah satu kelas dan MENOMORI ULANG sisanya:

    lama : {0: B_GREEN, 1: B_RED}
    ->   : {0: BOX_biru, 1: BOX_ijo, 2: B_GREEN,  3: B_RED}
    baru : {0: BOX_biru, 1: BOX_ijo, 2: B_BLUE,   3: B_GREEN, 4: B_RED}

Dua kali berturut-turut indeks bola bergeser. Yang diuji di sini bukan "apakah
bola biru terdeteksi" melainkan dua hal yang gagalnya DIAM: apakah pemetaan
nama→peran masih benar setelah penggeseran, dan apakah bola biru benar-benar
tidak ikut menggerakkan kemudi.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from vision.class_map import (
    ALL_ROLES,
    BOX_ROLES,
    GATE_BUOY_ROLES,
    ROLE_BLUE_BOX,
    ROLE_BLUE_BUOY,
    ROLE_GREEN_BOX,
    ROLE_GREEN_BUOY,
    ROLE_RED_BUOY,
    build_role_map,
    role_of,
)
from vision.gate_convention import side_of

NAMA_MODEL_BARU = {0: "BOX_biru", 1: "BOX_ijo", 2: "B_BLUE", 3: "B_GREEN", 4: "B_RED"}
NAMA_MODEL_LAMA = {0: "B_GREEN", 1: "B_RED"}

LEBAR, TINGGI = 1920, 1080


class UjiPemetaanKelas(unittest.TestCase):

    def test_model_baru_dipetakan_lengkap(self):
        peta = build_role_map(NAMA_MODEL_BARU)
        self.assertEqual(peta, {
            0: ROLE_BLUE_BOX,
            1: ROLE_GREEN_BOX,
            2: ROLE_BLUE_BUOY,
            3: ROLE_GREEN_BUOY,
            4: ROLE_RED_BUOY,
        })

    def test_penggeseran_indeks_tidak_menukar_warna(self):
        """
        Inti dari seluruh modul class_map: indeks bola bergeser antar model, nama
        tidak. Kalau ini gagal, kapal mengemudi ke gerbang yang salah tanpa error.
        """
        lama = build_role_map(NAMA_MODEL_LAMA)
        baru = build_role_map(NAMA_MODEL_BARU)
        self.assertEqual(lama[0], ROLE_GREEN_BUOY)
        self.assertEqual(baru[3], ROLE_GREEN_BUOY, "hijau pindah dari 0 ke 3")
        self.assertEqual(lama[1], ROLE_RED_BUOY)
        self.assertEqual(baru[4], ROLE_RED_BUOY, "merah pindah dari 1 ke 4")
        # Indeks 0 dan 1 sekarang BOX. Kalau pemetaan berbasis indeks, keduanya
        # akan terbaca sebagai bola hijau & merah.
        self.assertIn(baru[0], BOX_ROLES)
        self.assertIn(baru[1], BOX_ROLES)

    def test_ejaan_lain_bola_biru_tetap_dikenali(self):
        for nama in ("B_BLUE", "b_blue", "blue", "Blue_Ball", "BOLA_BIRU"):
            with self.subTest(nama=nama):
                self.assertEqual(role_of(nama), ROLE_BLUE_BUOY)

    def test_kelas_asing_dibuang_bukan_ditebak(self):
        peta = build_role_map({0: "B_GREEN", 1: "entah_apa"})
        self.assertEqual(peta, {0: ROLE_GREEN_BUOY})

    def test_bola_biru_bukan_penanda_gerbang(self):
        """Kalau ini gagal, bola biru ikut menggerakkan Gate State Machine."""
        self.assertNotIn(ROLE_BLUE_BUOY, GATE_BUOY_ROLES)
        self.assertIn(ROLE_BLUE_BUOY, ALL_ROLES)

    def test_bola_biru_belum_punya_sisi_lintasan(self):
        """
        Perannya di arena belum ditentukan. Memberinya sisi sekarang = menebak, dan
        tebakan di tabel ini berubah jadi kemudi yang salah arah tanpa suara.
        """
        for warna in ("green", "red", "blue_box", "green_box"):
            self.assertIn(side_of(warna), ("left", "right"))
        with self.assertRaises(KeyError):
            side_of("blue")


class ModelPalsu:
    """YOLO palsu: mengembalikan deteksi yang sudah ditentukan, tanpa bobot apa pun."""

    def __init__(self, names, deteksi):
        self.names = names
        self._deteksi = deteksi

    def __call__(self, frame, **kwargs):
        class _Box:
            def __init__(self, cls, xyxy):
                self.cls = [cls]
                self.conf = [0.9]
                self.xyxy = [xyxy]

        class _Result:
            def __init__(self, boxes):
                self.boxes = boxes

        return iter([_Result([_Box(c, xy) for c, xy in self._deteksi])])


def kotak(cx, sisi=200):
    """xyxy di tengah vertikal frame, dengan lebar/tinggi `sisi`."""
    return [cx - sisi // 2, TINGGI // 2 - sisi // 2, cx + sisi // 2, TINGGI // 2 + sisi // 2]


class UjiTrackerBolaBiru(unittest.TestCase):
    """
    Tracker diuji dengan model palsu supaya yang dinilai adalah LOGIKA pemilahannya,
    bukan kualitas deteksi YOLO.
    """

    def tracker(self, deteksi):
        from vision.tracker import BallTracker
        t = BallTracker.__new__(BallTracker)          # lewati pemuatan bobot
        t.model = ModelPalsu(NAMA_MODEL_BARU, deteksi)
        t.conf_threshold = 0.5
        t.min_detection_area_px2 = 100.0
        t._role_of_class = build_role_map(NAMA_MODEL_BARU)
        return t

    def proses(self, deteksi):
        t = self.tracker(deteksi)
        frame = np.zeros((TINGGI, LEBAR, 3), dtype=np.uint8)
        _, gate_x, _, balls, boxes = t.process_frame(frame)
        return gate_x, balls, boxes

    def test_bola_biru_sampai_ke_keluaran(self):
        _, balls, _ = self.proses([(2, kotak(500)), (2, kotak(900, 300))])
        self.assertEqual(len(balls["blue"]), 2)
        self.assertEqual(balls["red"], [])
        self.assertEqual(balls["green"], [])

    def test_bola_biru_diurutkan_terbesar_dulu(self):
        _, balls, _ = self.proses([(2, kotak(500, 100)), (2, kotak(900, 400))])
        luas = [(b[4] - b[2]) * (b[5] - b[3]) for b in balls["blue"]]
        self.assertEqual(luas, sorted(luas, reverse=True))

    def test_bola_biru_TIDAK_menggeser_midpoint_fallback(self):
        """
        Ini uji terpenting di berkas ini.

        Fallback midpoint menyala saat >= 2 penanda gerbang terlihat tanpa pasangan
        merah-hijau. Kalau bola biru ikut terhitung, kemudi kapal tertarik ke arahnya
        di sepanjang lintasan buoy — tanpa satu pun pesan error.
        """
        # Dua bola biru saja: tidak ada gerbang, jadi tidak ada midpoint sama sekali.
        gate_x, _, _ = self.proses([(2, kotak(300)), (2, kotak(1600))])
        self.assertIsNone(gate_x, "dua bola biru tidak boleh membentuk midpoint")

        # Satu bola hijau + dua bola biru: midpoint HARUS murni dari yang hijau.
        gate_hanya_hijau, _, _ = self.proses([(3, kotak(600))])
        gate_dengan_biru, _, _ = self.proses(
            [(3, kotak(600)), (2, kotak(1800)), (2, kotak(1750))])
        self.assertEqual(gate_dengan_biru, gate_hanya_hijau,
                         "bola biru menggeser midpoint — kemudi akan ikut melenceng")

    def test_pasangan_gerbang_tetap_murni_merah_hijau(self):
        gate_bersih, _, _ = self.proses([(3, kotak(700)), (4, kotak(1300))])
        gate_ada_biru, _, _ = self.proses(
            [(3, kotak(700)), (4, kotak(1300)), (2, kotak(200)), (2, kotak(1900))])
        self.assertEqual(gate_ada_biru, gate_bersih)
        self.assertEqual(gate_bersih, 1000, "midpoint 700 & 1300 seharusnya 1000")

    def test_box_juga_tetap_tidak_menggeser_midpoint(self):
        """Perilaku lama tidak boleh ikut berubah saat daftar-hitam jadi daftar-putih."""
        gate_hanya_hijau, _, _ = self.proses([(3, kotak(600))])
        gate_dengan_box, _, _ = self.proses(
            [(3, kotak(600)), (0, kotak(1800)), (1, kotak(1750))])
        self.assertEqual(gate_dengan_box, gate_hanya_hijau)

    def test_box_dan_bola_tidak_tertukar(self):
        _, balls, boxes = self.proses([
            (0, kotak(200)), (1, kotak(400)), (2, kotak(600)),
            (3, kotak(800)), (4, kotak(1000)),
        ])
        self.assertEqual(len(boxes[ROLE_BLUE_BOX]), 1)
        self.assertEqual(len(boxes[ROLE_GREEN_BOX]), 1)
        self.assertEqual(len(balls["blue"]), 1)
        self.assertEqual(len(balls["green"]), 1)
        self.assertEqual(len(balls["red"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
