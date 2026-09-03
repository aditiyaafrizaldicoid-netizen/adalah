"""
Uji pemilih lintasan arena (A / B).

Jalankan:  python3 tools/uji_lintasan.py

Konvensi sisi menentukan ke arah mana kapal membanting saat hanya SATU penanda
terlihat. Memilih lintasan yang keliru tidak memunculkan error apa pun — kapal
tetap berlayar, hanya saja setiap koreksi "menjauhi bola" berubah jadi "menuju
bola". Karena itu yang diuji di sini bukan sekadar "nilainya berubah", melainkan
bahwa seluruh turunan konvensi ikut berbalik, dan bahwa perubahan itu tidak bisa
terjadi pada saat yang berbahaya.
"""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision import gate_convention as gc
from vision.gate_convention import (
    LEFT, RIGHT, channel_sign, side_of, steer_sign_toward, virtual_gate_center_x,
)

PENANDA = ("green", "red", "blue_box", "green_box")


class UjiTabelLintasan(unittest.TestCase):

    def setUp(self):
        gc.set_lintasan("B")

    def tearDown(self):
        gc.set_lintasan("B")

    def test_bawaan_adalah_B(self):
        """
        B adalah konfigurasi kapal SEBELUM pemilih ini ada. Kapal yang belum
        pernah menerima perintah apa pun harus berperilaku persis seperti dulu.
        """
        import importlib
        modul = importlib.reload(gc)
        self.assertEqual(modul.lintasan_aktif(), "B")

    def test_lintasan_B_sesuai_arena_sekarang(self):
        gc.set_lintasan("B")
        self.assertEqual(side_of("green"), LEFT)
        self.assertEqual(side_of("red"), RIGHT)
        self.assertEqual(side_of("blue_box"), RIGHT)
        self.assertEqual(side_of("green_box"), LEFT)

    def test_lintasan_A_sesuai_permintaan(self):
        gc.set_lintasan("A")
        self.assertEqual(side_of("green"), RIGHT)
        self.assertEqual(side_of("red"), LEFT)
        self.assertEqual(side_of("blue_box"), LEFT)
        self.assertEqual(side_of("green_box"), RIGHT)

    def test_A_dan_B_benar_benar_saling_berkebalikan(self):
        """Kalau ada satu penanda yang tidak ikut terbalik, kapal akan mencari
        celah yang tidak ada — dua penanda menunjuk sisi yang sama."""
        gc.set_lintasan("A")
        a = {p: side_of(p) for p in PENANDA}
        gc.set_lintasan("B")
        b = {p: side_of(p) for p in PENANDA}
        for p in PENANDA:
            with self.subTest(penanda=p):
                self.assertNotEqual(a[p], b[p], f"{p} tidak ikut berbalik")

    def test_setiap_lintasan_punya_dua_sisi_seimbang(self):
        """Empat penanda, dua di kiri dua di kanan — di kedua lintasan."""
        for nama in gc.daftar_lintasan():
            gc.set_lintasan(nama)
            sisi = [side_of(p) for p in PENANDA]
            with self.subTest(lintasan=nama):
                self.assertEqual(sisi.count(LEFT), 2)
                self.assertEqual(sisi.count(RIGHT), 2)

    def test_bola_dan_box_sewarna_menandai_sisi_yang_sama(self):
        """
        Bola hijau dan box hijau harus menandai tepi yang sama, begitu pula
        merah dengan biru. Kalau tidak, kapal berpindah alur saat beralih dari
        bagian buoy ke bagian box.
        """
        for nama in gc.daftar_lintasan():
            gc.set_lintasan(nama)
            with self.subTest(lintasan=nama):
                self.assertEqual(side_of("green"), side_of("green_box"))
                self.assertEqual(side_of("red"), side_of("blue_box"))


class UjiTurunanKonvensi(unittest.TestCase):
    """Semua yang menghitung arah HARUS ikut berbalik, bukan cuma tabelnya."""

    def tearDown(self):
        gc.set_lintasan("B")

    def test_channel_sign_ikut_berbalik(self):
        gc.set_lintasan("B")
        b = {p: channel_sign(p) for p in PENANDA}
        gc.set_lintasan("A")
        a = {p: channel_sign(p) for p in PENANDA}
        for p in PENANDA:
            with self.subTest(penanda=p):
                self.assertEqual(a[p], -b[p])

    def test_titik_tengah_semu_pindah_ke_seberang(self):
        """
        Inti kemudi saat satu bola terlihat. Di B, bola hijau menandai tepi KIRI
        sehingga titik lewatnya ada di KANAN bola; di A sebaliknya.
        """
        gc.set_lintasan("B")
        b = virtual_gate_center_x(ball_x=1000, color="green", half_gate_px=200)
        gc.set_lintasan("A")
        a = virtual_gate_center_x(ball_x=1000, color="green", half_gate_px=200)
        self.assertEqual(b, 1200.0)
        self.assertEqual(a, 800.0)

    def test_steer_sign_toward_tetap_murni_soal_sisi(self):
        """Fungsi ini menerjemahkan SISI, bukan warna — tidak boleh ikut berubah."""
        for nama in gc.daftar_lintasan():
            gc.set_lintasan(nama)
            self.assertEqual(steer_sign_toward(LEFT), -1.0)
            self.assertEqual(steer_sign_toward(RIGHT), 1.0)

    def test_bola_biru_tetap_tanpa_sisi_di_kedua_lintasan(self):
        """Perannya belum ditentukan — jangan sampai diam-diam kebagian sisi."""
        for nama in gc.daftar_lintasan():
            gc.set_lintasan(nama)
            with self.subTest(lintasan=nama), self.assertRaises(KeyError):
                side_of("blue")


class UjiPergantian(unittest.TestCase):

    def setUp(self):
        gc.set_lintasan("B")

    def tearDown(self):
        gc.set_lintasan("B")

    def test_nama_tidak_dikenal_ditolak_tanpa_mengubah_apa_pun(self):
        for buruk in ("C", "", None, "AA", "1", "kiri"):
            with self.subTest(nilai=buruk):
                self.assertFalse(gc.set_lintasan(buruk))
                self.assertEqual(gc.lintasan_aktif(), "B")

    def test_huruf_kecil_dan_spasi_diterima(self):
        self.assertTrue(gc.set_lintasan("  a  "))
        self.assertEqual(gc.lintasan_aktif(), "A")

    def test_memilih_lintasan_yang_sama_bukan_perubahan(self):
        self.assertFalse(gc.set_lintasan("B"), "tidak ada yang berubah")
        self.assertEqual(gc.lintasan_aktif(), "B")

    def test_sisi_lintasan_mengembalikan_salinan(self):
        """Pemanggil yang mengubah hasilnya tidak boleh merusak tabel aslinya."""
        salinan = gc.sisi_lintasan("A")
        salinan["green"] = "rusak"
        gc.set_lintasan("A")
        self.assertEqual(side_of("green"), RIGHT)

    def _adu_thread(self, baca_sekali):
        """Jalankan `baca_sekali()` di 4 thread selagi lintasan diganti 3000 kali."""
        rusak = []
        berhenti = threading.Event()

        def pembaca():
            while not berhenti.is_set():
                hasil = baca_sekali()
                if hasil is not None:
                    rusak.append(hasil)

        t = [threading.Thread(target=pembaca) for _ in range(4)]
        for x in t:
            x.start()
        for i in range(3000):
            gc.set_lintasan("A" if i % 2 else "B")
        berhenti.set()
        for x in t:
            x.join(timeout=5)
        return rusak

    def test_snapshot_selalu_konsisten_walau_diganti_terus(self):
        """
        Jaminan yang SUNGGUHAN: snapshot() mengambil rujukan tabel sekali, jadi
        seluruh isinya pasti dari lintasan yang sama. Dua kiri, dua kanan, dan
        bola sewarna dengan box-nya selalu sepakat.
        """
        def sekali():
            t = gc.snapshot()
            sisi = [t[p] for p in PENANDA]
            if sisi.count(LEFT) != 2 or sisi.count(RIGHT) != 2:
                return sisi
            if t["green"] != t["green_box"] or t["red"] != t["blue_box"]:
                return sisi
            return None

        rusak = self._adu_thread(sekali)
        self.assertEqual(rusak, [], f"{len(rusak)} snapshot tertangkap campur")

    def test_pembacaan_tunggal_tidak_pernah_rusak_atau_melempar(self):
        """
        Yang dijamin per panggilan: nilainya SELALU salah satu sisi yang sah dan
        tidak pernah melempar. Yang TIDAK dijamin adalah keselarasan antar
        panggilan terpisah — untuk itu ada snapshot(); lihat catatannya di
        vision/gate_convention.py.
        """
        def sekali():
            nilai = side_of("green")
            return None if nilai in (LEFT, RIGHT) else nilai

        rusak = self._adu_thread(sekali)
        self.assertEqual(rusak, [], "pembacaan tunggal menghasilkan nilai tidak sah")


class MesinMisiPalsu:
    def __init__(self, status="IDLE"):
        self.status = status


class UjiPerintahWebSocket(unittest.TestCase):
    """Penjaga di sisi perintah: kapan pergantian BOLEH dijalankan."""

    def setUp(self):
        from connection.websocket import ASVWebSocketClient
        gc.set_lintasan("B")
        self.ws = ASVWebSocketClient.__new__(ASVWebSocketClient)
        self.ws.mission_engine = MesinMisiPalsu("IDLE")
        self.terkirim = []
        self.peringatan = []
        self.ws._send_ws = lambda pesan: self.terkirim.append(pesan)
        self.ws._send_warning = lambda *a, **k: self.peringatan.append((a, k))

    def tearDown(self):
        gc.set_lintasan("B")

    def ack(self):
        return [p for p in self.terkirim if p.get("type") == "TRACK_CONFIG"][-1]["payload"]

    def test_pergantian_biasa_diterapkan_dan_dibalas(self):
        self.ws._terapkan_lintasan("A")
        self.assertEqual(gc.lintasan_aktif(), "A")
        a = self.ack()
        self.assertTrue(a["ok"])
        self.assertEqual(a["track"], "A")
        self.assertEqual(a["sides"]["green"], RIGHT)

    def test_DITOLAK_selagi_misi_berjalan(self):
        """
        Membalik konvensi di tengah misi membalik SEKETIKA arah setiap koreksi
        kemudi yang sedang berjalan — manuver menjauhi bola berubah jadi menuju
        bola, pada jarak yang sudah dekat.
        """
        self.ws.mission_engine = MesinMisiPalsu("RUNNING")
        self.ws._terapkan_lintasan("A")
        self.assertEqual(gc.lintasan_aktif(), "B", "lintasan TIDAK boleh berubah")
        a = self.ack()
        self.assertFalse(a["ok"])
        self.assertEqual(a["track"], "B", "balasan harus menyebut yang BENAR-BENAR aktif")
        self.assertIn("misi", a["reason"].lower())

    def test_memilih_yang_sudah_aktif_tetap_boleh_walau_misi_berjalan(self):
        """Bukan perubahan, jadi tidak ada bahaya — dan dashboard perlu jawaban."""
        self.ws.mission_engine = MesinMisiPalsu("RUNNING")
        self.ws._terapkan_lintasan("B")
        self.assertTrue(self.ack()["ok"])
        self.assertEqual(gc.lintasan_aktif(), "B")

    def test_nama_ngawur_dibalas_gagal_tanpa_mengubah(self):
        self.ws._terapkan_lintasan("Z")
        self.assertEqual(gc.lintasan_aktif(), "B")
        a = self.ack()
        self.assertFalse(a["ok"])
        self.assertIn("tidak dikenal", a["reason"].lower())

    def test_balasan_selalu_menyebut_lintasan_yang_aktif(self):
        """Dashboard tidak boleh pernah menampilkan setelan yang sebenarnya ditolak."""
        for nilai in ("A", "Z", "b", None):
            self.ws._terapkan_lintasan(nilai)
            with self.subTest(nilai=nilai):
                self.assertEqual(self.ack()["track"], gc.lintasan_aktif())

    def test_tanpa_mission_engine_tidak_crash(self):
        self.ws.mission_engine = None
        self.ws._terapkan_lintasan("A")
        self.assertEqual(gc.lintasan_aktif(), "A")


if __name__ == "__main__":
    unittest.main(verbosity=2)
