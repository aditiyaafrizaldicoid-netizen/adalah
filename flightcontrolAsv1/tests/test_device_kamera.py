"""
Uji penerjemah penunjuk perangkat kamera (camera/device.py).

Jalankan:  make test-unit

KENAPA ADA (kejadian nyata, 16 September 2026): kamera bawah air kemasukan air
lalu diganti unit lain. Nama by-id memuat NOMOR SERI perangkat, jadi path di .env
menunjuk kamera yang sudah tidak ada. Kapal tetap berjalan, foto tetap jadi, tetap
ber-geo-tag, tetap terkirim ke dashboard — hanya diambil kamera PERMUKAAN.

Tidak ada yang error. Satu-satunya petunjuk adalah satu baris di konsol Mini PC
yang berbunyi "tidak ada saat boot — tetap dicoba dibuka", dan baris itu tidak
menyebutkan apa yang sebenarnya terpasang. Mengganti kamera adalah perawatan
biasa, bukan kejadian langka, jadi jalur ini akan dilalui lagi.

Yang dikunci di sini: perangkat yang hilang HARUS menyebut apa yang tersedia.
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from camera import device


class UjiParse(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="uji_byid_")
        self._asli = device.DIR_BY_ID
        device.DIR_BY_ID = self.dir

    def tearDown(self):
        device.DIR_BY_ID = self._asli
        shutil.rmtree(self.dir, ignore_errors=True)

    def pasang(self, *nama):
        """Pura-pura kamera dengan nama ini sedang tertancap."""
        for n in nama:
            open(os.path.join(self.dir, n), "w").close()

    def parse_dgn_keluaran(self, raw, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            hasil = device.parse(raw, **kw)
        return hasil, buf.getvalue()

    # ── Bentuk nilai ────────────────────────────────────────────────────────

    def test_angka_jadi_index(self):
        self.assertEqual(device.parse("2"), 2)

    def test_kosong_jadi_default(self):
        self.assertIsNone(device.parse(""))
        self.assertEqual(device.parse("   ", default=7), 7)
        self.assertIsNone(device.parse(None))

    def test_bukan_angka_path_maupun_nama_yang_cocok_jadi_default(self):
        # Menegaskan HASILNYA, bukan kalimat pesannya: kata-kata boleh diperbaiki,
        # yang tidak boleh berubah diam-diam adalah nilai yang dikembalikan.
        hasil, keluaran = self.parse_dgn_keluaran("kamera-bawah", default=1)
        self.assertEqual(hasil, 1)
        self.assertIn("tidak cocok", keluaran)

    def test_path_yang_ADA_dikembalikan_apa_adanya(self):
        self.pasang("usb-Logitech_C270-video-index0")
        p = os.path.join(self.dir, "usb-Logitech_C270-video-index0")
        hasil, keluaran = self.parse_dgn_keluaran(p)
        self.assertEqual(hasil, p)
        self.assertNotIn("TIDAK ADA", keluaran)

    # ── Perangkat hilang ────────────────────────────────────────────────────

    def test_path_yang_HILANG_tetap_dikembalikan(self):
        # Sengaja tetap dikembalikan, bukan dijadikan None: percobaan membukanya
        # akan gagal dengan bunyi, sementara diam-diam menjadikannya None membuat
        # kamera bawah air "tidak terpasang" — yang di sistem ini berarti TIDAK
        # dianggap kegagalan sama sekali.
        p = os.path.join(self.dir, "usb-sudah-dicabut-video-index0")
        hasil, _ = self.parse_dgn_keluaran(p)
        self.assertEqual(hasil, p)

    def test_perangkat_hilang_menyebutkan_yang_TERPASANG(self):
        # Inti berkas uji ini. Operator yang baru mengganti kamera butuh NAMA
        # penggantinya, bukan konfirmasi bahwa yang lama hilang.
        self.pasang("usb-046d_MX_Brio_2605ZB327V68-video-index0",
                    "usb-046d_C270_HD_WEBCAM_0EE94070-video-index0")
        _, keluaran = self.parse_dgn_keluaran(
            os.path.join(self.dir, "usb-JETE-W7_JETE-W7_202503051344-video-index0"),
            nama_env="ASV_UNDERWATER_CAMERA_INDEX")

        self.assertIn("TIDAK ADA", keluaran)
        self.assertIn("ASV_UNDERWATER_CAMERA_INDEX", keluaran)
        self.assertIn("usb-046d_C270_HD_WEBCAM_0EE94070-video-index0", keluaran)
        self.assertIn("usb-046d_MX_Brio_2605ZB327V68-video-index0", keluaran)

    def test_tidak_ada_kamera_sama_sekali_menyarankan_periksa_kabel(self):
        _, keluaran = self.parse_dgn_keluaran(
            os.path.join(self.dir, "usb-entah-video-index0"))
        self.assertIn("periksa kabel", keluaran.lower())

    def test_direktori_by_id_tidak_ada_tidak_melempar(self):
        # Mesin tanpa perangkat V4L sama sekali (mis. laptop pengembang di dalam
        # container) tidak punya /dev/v4l/by-id. Itu tidak boleh menjatuhkan boot.
        device.DIR_BY_ID = "/jalan/yang/tidak/pernah/ada"
        self.assertEqual(device.daftar_tersedia(), [])
        hasil, _ = self.parse_dgn_keluaran("/dev/video9")
        self.assertEqual(hasil, "/dev/video9")


class UjiSama(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="uji_sama_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_dua_nama_untuk_satu_perangkat_dianggap_sama(self):
        # by-id adalah symlink ke /dev/videoN. Membandingkan teksnya saja akan
        # melewatkan kasus kamera permukaan dan bawah air menunjuk perangkat yang
        # SAMA — yang berarti kapal mencari bola di pemandangan bawah air.
        asli = os.path.join(self.dir, "video0")
        open(asli, "w").close()
        tautan = os.path.join(self.dir, "usb-kamera-video-index0")
        os.symlink(asli, tautan)
        self.assertTrue(device.sama(tautan, asli))

    def test_perangkat_berbeda_tidak_dianggap_sama(self):
        a = os.path.join(self.dir, "video0")
        b = os.path.join(self.dir, "video2")
        open(a, "w").close()
        open(b, "w").close()
        self.assertFalse(device.sama(a, b))

    def test_angka_sama(self):
        self.assertTrue(device.sama(2, 2))
        self.assertFalse(device.sama(2, 3))

    def test_angka_dan_path_tidak_dibandingkan_silang(self):
        # Tidak bisa dipastikan tanpa membuka perangkatnya, jadi jangan menebak.
        self.assertFalse(device.sama(0, "/dev/video0"))


class UjiCocokNama(unittest.TestCase):
    """
    Potongan nama sebagai isi .env.

    Nama by-id memuat nomor seri, jadi mengganti kamera dengan unit lain bermodel
    SAMA sudah cukup membuat .env menunjuk perangkat yang tidak ada. Pada kapal ini
    itu terjadi dua kali dalam sepekan — kamera bawah air kemasukan air, ditukar,
    dan serinya berubah dari 0EE94070 ke 602C4070. Foto tetap jadi setiap kali,
    dari kamera permukaan, tanpa satu pun error.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="uji_cocok_")
        self._asli = device.DIR_BY_ID
        device.DIR_BY_ID = self.dir
        for n in ("usb-046d_C270_HD_WEBCAM_602C4070-video-index0",
                  "usb-046d_C270_HD_WEBCAM_602C4070-video-index1",
                  "usb-046d_MX_Brio_2605ZB327V68-video-index0",
                  "usb-046d_MX_Brio_2605ZB327V68-video-index1"):
            open(os.path.join(self.dir, n), "w").close()

    def tearDown(self):
        device.DIR_BY_ID = self._asli
        shutil.rmtree(self.dir, ignore_errors=True)

    def diam(self, raw, **kw):
        with redirect_stdout(io.StringIO()):
            return device.parse(raw, **kw)

    def test_potongan_nama_menemukan_perangkatnya(self):
        self.assertEqual(
            self.diam("C270"),
            os.path.join(self.dir, "usb-046d_C270_HD_WEBCAM_602C4070-video-index0"))

    def test_memilih_node_penangkap_bukan_index1(self):
        # Tiap kamera juga mendaftarkan index1 yang BUKAN sumber frame. Memilihnya
        # menghasilkan kamera yang "terbuka" tapi tidak pernah memberi gambar —
        # yang di sistem ini berakhir sebagai foto permukaan diam-diam.
        self.assertTrue(self.diam("C270").endswith("-video-index0"))

    def test_tidak_peduli_huruf_besar_kecil(self):
        self.assertEqual(self.diam("c270"), self.diam("C270"))

    def test_potongan_ambigu_DITOLAK_bukan_ditebak(self):
        # "046d" adalah kode vendor Logitech — cocok dengan KEDUA kamera. Menebak
        # salah satu berarti kamera permukaan dan bawah air bisa tertukar tanpa
        # satu pun pesan.
        self.assertIsNone(self.diam("046d"))

    def test_potongan_ambigu_menyebutkan_kandidatnya(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            device.parse("046d", nama_env="ASV_UNDERWATER_CAMERA_INDEX")
        keluaran = buf.getvalue()
        self.assertIn("LEBIH DARI SATU", keluaran)
        self.assertIn("C270", keluaran)
        self.assertIn("MX_Brio", keluaran)

    def test_potongan_yang_tidak_cocok_menyebutkan_yang_tersedia(self):
        # Ejaan kamera LAMA yang sudah dicabut — kasus nyata yang melahirkan ini.
        buf = io.StringIO()
        with redirect_stdout(buf):
            hasil = device.parse("JETE-W7", nama_env="ASV_UNDERWATER_CAMERA_INDEX")
        self.assertIsNone(hasil)
        self.assertIn("C270", buf.getvalue())

    def test_path_lengkap_tetap_menang_atas_pencocokan_nama(self):
        # Yang menulis path lengkap berhak mendapat persis itu.
        penuh = os.path.join(self.dir, "usb-046d_MX_Brio_2605ZB327V68-video-index0")
        self.assertEqual(self.diam(penuh), penuh)

    def test_angka_tetap_angka(self):
        self.assertEqual(self.diam("2"), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
