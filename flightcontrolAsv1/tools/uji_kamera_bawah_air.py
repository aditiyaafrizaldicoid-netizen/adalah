"""
Uji pemotretan box biru dengan kamera bawah air.

Jalankan:  python3 tools/uji_kamera_bawah_air.py

Box biru adalah target BAWAH AIR menurut ketentuan lomba. Sebelum kameranya
terpasang, ia difoto dari permukaan karena bagiannya memang menyembul — solusi
sementara, bukan yang dinilai.

Kegagalan yang dijaga berkas ini semuanya diam:
  - foto permukaan yang menyamar sebagai foto bawah air (bukti palsu);
  - frame BASI dari kamera yang membeku, tersimpan sebagai foto box biru padahal
    isinya pemandangan menit-menit sebelumnya — tampak sah, mustahil dibedakan
    setelah lomba;
  - box hijau ikut-ikutan difoto dari bawah air.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from camera.underwater import UnderwaterCamera, dari_env
from control.mission_engine import MissionEngine
from vision.class_map import ROLE_BLUE_BOX, ROLE_GREEN_BOX


def frame_warna(nilai_biru):
    """Frame polos yang bisa dibedakan dari frame lain lewat nilai pikselnya."""
    f = np.zeros((120, 160, 3), dtype=np.uint8)
    f[:, :, 0] = nilai_biru
    return f


FRAME_PERMUKAAN = frame_warna(10)
FRAME_BAWAH_AIR = frame_warna(200)


class KameraBawahAirPalsu:
    def __init__(self, frame=None, umur=0.0):
        self._frame = frame
        self._umur = umur

    def is_ok(self):
        return self._frame is not None and self._umur <= UnderwaterCamera.UMUR_MAKS_DETIK

    def umur_frame_detik(self):
        return float("inf") if self._frame is None else self._umur

    def ambil_frame(self):
        return None if not self.is_ok() else self._frame.copy()


class Tel:
    mode = "MANUAL"


class AsvPalsu:
    def is_connected(self): return True
    def get_telemetry(self): return Tel()
    def get_telemetry_dict(self): return {"lat": -7.92, "lon": 112.59, "heading": 90.0}
    def set_mode(self, m): return True
    def stop_movement(self, silent=False): return True


class Ctl:
    def reset(self): pass


class UjiPemilihanSumber(unittest.TestCase):
    """Frame mana yang dipakai untuk label apa."""

    def setUp(self):
        self.e = MissionEngine(AsvPalsu(), None, Ctl(),
                               camera_width=1280, camera_height=720)

    def pilih(self, label):
        return self.e._sumber_foto(FRAME_PERMUKAAN, label)

    def test_box_biru_memakai_kamera_bawah_air(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        frame, sumber, imbuhan = self.pilih(ROLE_BLUE_BOX)
        self.assertEqual(frame[0, 0, 0], 200, "frame yang dipakai bukan dari bawah air")
        self.assertEqual(sumber, "bawah air")
        self.assertEqual(imbuhan, "_bawahair")

    def test_box_hijau_TETAP_kamera_permukaan(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        frame, sumber, imbuhan = self.pilih(ROLE_GREEN_BOX)
        self.assertEqual(frame[0, 0, 0], 10)
        self.assertEqual(sumber, "permukaan")
        self.assertEqual(imbuhan, "")

    def test_take_image_biasa_tetap_kamera_permukaan(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        frame, sumber, _ = self.pilih("step_dermaga")
        self.assertEqual(frame[0, 0, 0], 10)
        self.assertEqual(sumber, "permukaan")

    def test_kamera_tidak_terpasang_jatuh_ke_permukaan_dan_DITANDAI(self):
        frame, sumber, imbuhan = self.pilih(ROLE_BLUE_BOX)
        self.assertEqual(frame[0, 0, 0], 10)
        self.assertIn("tidak dipasang", sumber)
        self.assertEqual(imbuhan, "_permukaan",
                         "foto permukaan yang menyamar jadi foto bawah air = bukti palsu")

    def test_tidak_dipasang_TIDAK_dilaporkan_sebagai_kegagalan(self):
        """
        Kapal yang sengaja berjalan tanpa kamera bawah air tidak boleh menandai
        setiap fotonya sebagai kegagalan. Peringatan yang muncul terus-menerus
        pada keadaan normal melatih operator mengabaikannya — lalu kegagalan yang
        SUNGGUHAN ikut terlewat.
        """
        _, tidak_dipasang, _ = self.pilih(ROLE_BLUE_BOX)
        self.assertNotIn("cadangan", tidak_dipasang)
        self.assertNotIn("gagal", tidak_dipasang)

        self.e.set_underwater_camera(KameraBawahAirPalsu(None))
        _, rusak, _ = self.pilih(ROLE_BLUE_BOX)
        self.assertIn("cadangan", rusak, "kamera yang dipasang tapi mati HARUS diperingatkan")
        self.assertNotEqual(tidak_dipasang, rusak,
                            "dua keadaan yang butuh tindakan berbeda harus terbaca berbeda")

    def test_frame_BASI_ditolak_dan_jatuh_ke_permukaan(self):
        """Kamera yang membeku tetap menyimpan frame terakhirnya di memori."""
        basi = KameraBawahAirPalsu(FRAME_BAWAH_AIR,
                                   umur=UnderwaterCamera.UMUR_MAKS_DETIK + 1)
        self.e.set_underwater_camera(basi)
        frame, sumber, imbuhan = self.pilih(ROLE_BLUE_BOX)
        self.assertEqual(frame[0, 0, 0], 10, "frame basi tidak boleh jadi foto")
        self.assertEqual(imbuhan, "_permukaan")

    def test_kamera_terpasang_tapi_belum_pernah_memberi_frame(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(None))
        _, sumber, imbuhan = self.pilih(ROLE_BLUE_BOX)
        self.assertIn("cadangan", sumber)
        self.assertEqual(imbuhan, "_permukaan")

    def test_underwater_siap_melaporkan_apa_adanya(self):
        self.assertFalse(self.e.underwater_siap, "belum terpasang")
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.assertTrue(self.e.underwater_siap)
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR, umur=99))
        self.assertFalse(self.e.underwater_siap, "frame basi bukan 'siap'")


class UjiBerkasTersimpan(unittest.TestCase):
    """Bukti yang bertahan setelah lomba: nama berkas & sidecar JSON."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="uji_capture_")
        self.e = MissionEngine(AsvPalsu(), None, Ctl(),
                               camera_width=1280, camera_height=720)
        self.e.CAPTURE_DIR = self.dir

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def potret(self, label, cam):
        self.e.set_underwater_camera(cam)
        self.e._capture_pending = True
        self.e._capture_label = label
        return self.e.capture_now(FRAME_PERMUKAAN)

    def test_foto_bawah_air_diberi_nama_dan_dicatat(self):
        path = self.potret(ROLE_BLUE_BOX, KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.assertIsNotNone(path)
        self.assertIn("blue_box_bawahair", os.path.basename(path))
        with open(path.replace(".jpg", ".json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["kamera"], "bawah air")

    def test_foto_permukaan_jujur_menyebut_kameranya(self):
        """Nama berkas & sidecar JSON tetap menyatakan ini foto permukaan."""
        path = self.potret(ROLE_BLUE_BOX, None)
        self.assertIn("blue_box_permukaan", os.path.basename(path))
        with open(path.replace(".jpg", ".json"), encoding="utf-8") as f:
            kamera = json.load(f)["kamera"]
        self.assertIn("permukaan", kamera)
        self.assertIn("tidak dipasang", kamera)

    def test_box_hijau_nama_berkasnya_tidak_berubah(self):
        path = self.potret(ROLE_GREEN_BOX, KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        nama = os.path.basename(path)
        self.assertIn("green_box", nama)
        self.assertNotIn("bawahair", nama)
        self.assertNotIn("permukaan", nama)

    def test_status_misi_melaporkan_kamera_foto_terakhir(self):
        self.potret(ROLE_BLUE_BOX, KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.assertEqual(self.e.get_status_dict()["last_photo_camera"], "bawah air")
        self.potret(ROLE_BLUE_BOX, None)
        self.assertIn("permukaan", self.e.get_status_dict()["last_photo_camera"])
        self.potret(ROLE_BLUE_BOX, KameraBawahAirPalsu(None))
        self.assertIn("cadangan", self.e.get_status_dict()["last_photo_camera"])

    def test_kedua_kamera_gagal_tidak_menjatuhkan_misi(self):
        self.e.set_underwater_camera(None)
        self.e._capture_pending = True
        self.e._capture_label = ROLE_BLUE_BOX
        self.assertIsNone(self.e.capture_now(None), "tidak melempar, cukup None")
        self.assertEqual(self.e.get_status_dict()["last_photo_camera"], "gagal")

    def test_shutter_hanya_sekali_per_permintaan(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.e._capture_pending = True
        self.e._capture_label = ROLE_BLUE_BOX
        self.assertIsNotNone(self.e.capture_now(FRAME_PERMUKAAN))
        self.assertIsNone(self.e.capture_now(FRAME_PERMUKAAN))


class UjiKelasKamera(unittest.TestCase):
    """Logika UnderwaterCamera sendiri, tanpa perangkat sungguhan."""

    def kamera(self, frame, umur_detik):
        c = UnderwaterCamera(index=9, width=320, height=240, fps=5)
        c._frame = frame
        c._frame_at = time.time() - umur_detik
        return c

    def test_frame_segar_diterima(self):
        c = self.kamera(FRAME_BAWAH_AIR, 0.1)
        self.assertTrue(c.is_ok())
        self.assertIsNotNone(c.ambil_frame())

    def test_frame_basi_ditolak(self):
        c = self.kamera(FRAME_BAWAH_AIR, UnderwaterCamera.UMUR_MAKS_DETIK + 0.5)
        self.assertFalse(c.is_ok())
        self.assertIsNone(c.ambil_frame())

    def test_belum_pernah_ada_frame(self):
        c = UnderwaterCamera(index=9)
        self.assertFalse(c.is_ok())
        self.assertIsNone(c.ambil_frame())
        self.assertEqual(c.umur_frame_detik(), float("inf"))

    def test_ambil_frame_mengembalikan_SALINAN(self):
        """
        Pemanggil menggambari frame-nya (overlay geo-tag). Menggambari buffer yang
        sama yang sedang ditulis thread pembaca akan merusak foto berikutnya.
        """
        c = self.kamera(FRAME_BAWAH_AIR, 0.1)
        salinan = c.ambil_frame()
        salinan[:, :, 0] = 0
        self.assertEqual(c.ambil_frame()[0, 0, 0], 200, "buffer asli ikut berubah")

    def test_stop_aman_walau_belum_pernah_start(self):
        UnderwaterCamera(index=9).stop()


class UjiKonfigurasiEnv(unittest.TestCase):

    def setUp(self):
        self.simpan = {k: os.environ.get(k) for k in (
            "ASV_UNDERWATER_CAMERA_INDEX", "ASV_UNDERWATER_WIDTH",
            "ASV_UNDERWATER_HEIGHT", "ASV_UNDERWATER_FPS")}

    def tearDown(self):
        for k, v in self.simpan.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_tanpa_env_fitur_MATI(self):
        """
        Kapal yang kamera bawah airnya belum terpasang tidak boleh berubah
        perilakunya hanya karena kodenya sudah ada.
        """
        os.environ.pop("ASV_UNDERWATER_CAMERA_INDEX", None)
        self.assertIsNone(dari_env())

    def test_index_dibaca_dari_env(self):
        os.environ["ASV_UNDERWATER_CAMERA_INDEX"] = "2"
        os.environ["ASV_UNDERWATER_FPS"] = "8"
        c = dari_env()
        self.assertEqual(c.index, 2)
        self.assertEqual(c.fps, 8)

    def test_index_ngawur_tidak_mengaktifkan_apa_pun(self):
        os.environ["ASV_UNDERWATER_CAMERA_INDEX"] = "video1"
        self.assertIsNone(dari_env(), "salah ketik jangan jadi kamera index 0")

    def test_ukuran_ngawur_jatuh_ke_default(self):
        os.environ["ASV_UNDERWATER_CAMERA_INDEX"] = "1"
        os.environ["ASV_UNDERWATER_WIDTH"] = "besar"
        self.assertEqual(dari_env().width, 1280)


class UjiPemicuTetapDariKameraAtas(unittest.TestCase):
    """
    Sifat yang diminta operator, dikunci di sini.

    Air di arena keruh. Kamera bawah air mungkin TIDAK melihat apa pun, dan itu
    tidak boleh menghalangi foto yang waktunya sudah tepat. Keputusan "jepret
    sekarang" datang MURNI dari deteksi kamera permukaan — persis seperti sebelum
    kamera bawah air ada. Kamera bawah air hanya menyediakan frame.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="uji_pemicu_")
        self.e = MissionEngine(AsvPalsu(), None, Ctl(),
                               camera_width=1280, camera_height=720)
        self.e.CAPTURE_DIR = self.dir

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def potret(self, cam):
        self.e.set_underwater_camera(cam)
        self.e._capture_pending = True
        self.e._capture_label = ROLE_BLUE_BOX
        return self.e.capture_now(FRAME_PERMUKAAN)

    def test_frame_bawah_air_KOSONG_tetap_difoto(self):
        """Air keruh = frame gelap. Tetap frame yang sah, tetap disimpan."""
        gelap = np.zeros((120, 160, 3), dtype=np.uint8)
        path = self.potret(KameraBawahAirPalsu(gelap))
        self.assertIsNotNone(path, "frame gelap bukan alasan membatalkan foto")
        self.assertIn("bawahair", os.path.basename(path))

    def test_isi_frame_tidak_pernah_dinilai(self):
        """
        Tidak ada ambang kecerahan, kontras, atau 'ada objek tidak' di jalur ini.
        Apa pun isinya — putih polos sekalipun — disimpan apa adanya.
        """
        for isi in (0, 1, 127, 255):
            f = np.full((120, 160, 3), isi, dtype=np.uint8)
            with self.subTest(isi=isi):
                self.assertIsNotNone(self.potret(KameraBawahAirPalsu(f)))

    def test_shutter_TIDAK_menunggu_kamera_bawah_air(self):
        """
        capture_now selesai dalam panggilan yang sama, apa pun keadaan kamera
        bawah air. Menunggu berarti melewatkan momen yang sudah pas.
        """
        for cam in (None,
                    KameraBawahAirPalsu(None),
                    KameraBawahAirPalsu(FRAME_BAWAH_AIR, umur=99),
                    KameraBawahAirPalsu(FRAME_BAWAH_AIR)):
            self.e.set_underwater_camera(cam)
            self.e._capture_pending = True
            self.e._capture_label = ROLE_BLUE_BOX
            mulai = time.monotonic()
            self.e.capture_now(FRAME_PERMUKAAN)
            with self.subTest(cam=type(cam).__name__):
                self.assertLess(time.monotonic() - mulai, 0.5,
                                "capture_now menahan alur kontrol")
                self.assertFalse(self.e._capture_pending,
                                 "permintaan shutter tidak boleh menggantung")

    def test_keputusan_jepret_sama_persis_dengan_atau_tanpa_kamera_bawah_air(self):
        """
        Momen shutter ditentukan deteksi kamera atas. Memasang kamera bawah air
        tidak boleh menggeser momen itu satu frame pun.
        """
        def jalankan(cam):
            e = MissionEngine(AsvPalsu(), None, Ctl(),
                              camera_width=1280, camera_height=720)
            e.CAPTURE_DIR = self.dir
            e.set_underwater_camera(cam)
            e.load_mission([{"type": "BOX_APPROACH", "photo": "moving",
                             "target_area_px2": 50000, "center_tolerance_px": 100,
                             "evade_sec": 5.0}, {"type": "FINISH"}])
            e.start_mission()
            # Box biru di tengah frame dan sudah cukup dekat → syarat terpenuhi.
            box = (960, 540, 810, 390, 1110, 690)   # luas 300x300 = 90000 px²
            label = []
            for _ in range(3):
                _, _, lbl = e.update_frame(None, None,
                                           {"red": [], "green": [], "blue": []},
                                           {"blue_box": [box], "green_box": []})
                label.append(lbl)
            return label

        tanpa = jalankan(None)
        dengan = jalankan(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.assertEqual(
            [l.split("|")[1].strip().split()[0] for l in tanpa],
            [l.split("|")[1].strip().split()[0] for l in dengan],
            "urutan fase berubah gara-gara kamera bawah air terpasang")
        self.assertIn("SHOOT", tanpa[0], "syarat kamera atas seharusnya langsung memicu")


if __name__ == "__main__":
    unittest.main(verbosity=2)
