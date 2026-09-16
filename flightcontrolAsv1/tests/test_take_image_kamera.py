"""
Uji step TAKE_IMAGE memilih kameranya sendiri.

Jalankan:  make test-unit

TAKE_IMAGE memotret TANPA mencari apa pun — tidak ada box, tidak ada bola, tidak
ada deteksi yang harus berhasil dulu. Itu yang membedakannya dari PHOTO_BOX, dan
itu pula yang membuat kegagalannya sunyi: tidak ada sasaran yang "tidak ketemu",
jadi tidak ada yang bisa dilaporkan salah. Foto tetap tersimpan, tetap ber-geo-tag,
tetap muncul di dashboard — hanya diambil oleh kamera yang keliru.

Dua arah kekeliruan itu, keduanya dijaga di bawah:

  - Foto permukaan yang MENYAMAR sebagai foto bawah air. Ini bukti palsu. Kamera
    bawah air bisa tidak terpasang, atau terpasang tapi membeku, dan fotonya tetap
    jadi — dari permukaan. Nama berkas WAJIB berakhiran "_permukaan" dan sidecar
    JSON-nya WAJIB menyebut kejatuhan itu.

  - Misi lama yang diam-diam berpindah kamera. Setiap misi yang sudah tersimpan
    tidak punya field "kamera" sama sekali; bawaannya harus tetap permukaan,
    persis seperti sebelum pilihan ini ada.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from control.mission_engine import MissionEngine
from vision.class_map import ROLE_BLUE_BOX, ROLE_GREEN_BOX


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


# Dua frame yang SANGAT berbeda kecerahannya, supaya yang tersimpan bisa
# dibuktikan berasal dari kamera yang mana — bukan sekadar "ada berkasnya".
#
# UKURANNYA PENTING, dan ini pernah membuat uji di berkas ini lolos karena alasan
# yang salah. Overlay geo-tag menutupi sebagian gambar dengan teks; pada frame
# mungil 100x80 ia memakan porsi begitu besar sehingga foto PERMUKAAN yang cerah
# (200) turun rata-ratanya jadi 97,8 — di bawah ambang yang dipakai untuk
# membuktikan "ini foto bawah air". Ujinya lulus tanpa benar-benar membedakan apa
# pun. Pada 640x360 overlay hanya menggigit sedikit: 196,5 lawan 20,2.
FRAME_PERMUKAAN = np.full((360, 640, 3), 200, dtype=np.uint8)
FRAME_BAWAH_AIR = np.full((360, 640, 3), 20, dtype=np.uint8)

# Ambang yang memisahkan keduanya dengan jarak lebar, bukan pas-pasan.
TERANG_MIN = 150   # foto permukaan
GELAP_MAKS = 60    # foto bawah air


class KameraBawahAirPalsu:
    """Menirukan camera/underwater.py seperlunya."""

    def __init__(self, frame=None, umur=0.1):
        self._frame = frame
        self._umur = umur

    def ambil_frame(self):
        return self._frame

    def umur_frame_detik(self):
        return self._umur if self._frame is not None else float("inf")

    def is_ok(self):
        return self._frame is not None


class Dasar(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="uji_takeimage_")
        self.e = MissionEngine(AsvPalsu(), None, Ctl(),
                               camera_width=1280, camera_height=720)
        self.e.CAPTURE_DIR = self.dir

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def frame(self):
        return self.e.update_frame(None, None, {"red": [], "green": [], "blue": []})

    def buktikan_dari(self, path, kamera):
        """
        Buktikan foto tersimpan berasal dari kamera yang diharapkan.

        Membandingkan kecerahan, bukan piksel per piksel: overlay geo-tag memang
        menimpa sebagian gambar, jadi kesamaan persis mustahil. Yang dijaga adalah
        jaraknya tetap lebar — lihat catatan ukuran frame di atas.
        """
        import cv2
        rata = cv2.imread(path).mean()
        if kamera == "bawah air":
            self.assertLess(rata, GELAP_MAKS,
                            f"rata-rata {rata:.1f} — harusnya frame BAWAH AIR yang gelap")
        else:
            self.assertGreater(rata, TERANG_MIN,
                               f"rata-rata {rata:.1f} — harusnya frame PERMUKAAN yang terang")

    def jalankan_take_image(self, **field):
        """Jalankan TAKE_IMAGE sampai ia meminta shutter, tanpa melayaninya."""
        step = {"type": "TAKE_IMAGE", "name": "dermaga"}
        step.update(field)
        self.e.load_mission([step, {"type": "FINISH"}])
        self.e.start_mission()
        self.frame()


# ── Parser field "kamera" ───────────────────────────────────────────────────

class UjiParserKamera(Dasar):
    def test_tanpa_field_berarti_permukaan(self):
        # Misi yang sudah tersimpan tidak punya field ini. Bawaan apa pun selain
        # permukaan akan diam-diam mengubah arti misi yang sudah terbukti jalan.
        self.assertEqual(self.e._ti_kamera({}), MissionEngine.KAMERA_PERMUKAAN)

    def test_nilai_kosong_berarti_permukaan(self):
        self.assertEqual(self.e._ti_kamera({"kamera": ""}), MissionEngine.KAMERA_PERMUKAAN)
        self.assertEqual(self.e._ti_kamera({"kamera": None}), MissionEngine.KAMERA_PERMUKAAN)

    def test_nilai_tidak_dikenal_jatuh_ke_permukaan(self):
        # Salah ketik TIDAK boleh diam-diam berarti bawah air.
        self.assertEqual(self.e._ti_kamera({"kamera": "ngawur"}),
                         MissionEngine.KAMERA_PERMUKAAN)

    def test_ejaan_bawah_air_yang_diterima(self):
        for ejaan in ("bawah_air", "bawah air", "bawahair", "underwater", "uw",
                      "BAWAH_AIR", "  Underwater  "):
            with self.subTest(ejaan=ejaan):
                self.assertEqual(self.e._ti_kamera({"kamera": ejaan}),
                                 MissionEngine.KAMERA_BAWAH_AIR)

    def test_ejaan_permukaan_yang_diterima(self):
        for ejaan in ("permukaan", "atas", "atas_air", "surface", "SURFACE"):
            with self.subTest(ejaan=ejaan):
                self.assertEqual(self.e._ti_kamera({"kamera": ejaan}),
                                 MissionEngine.KAMERA_PERMUKAAN)


# ── Permintaan shutter membawa pilihan kameranya ────────────────────────────

class UjiPermintaanShutter(Dasar):
    def test_tanpa_pilihan_meminta_kamera_permukaan(self):
        self.jalankan_take_image()
        self.assertTrue(self.e.capture_pending)
        self.assertEqual(self.e._capture_kamera, MissionEngine.KAMERA_PERMUKAAN)

    def test_memilih_bawah_air_terbawa_ke_permintaan(self):
        # Yang melayani shutter adalah main.py beberapa frame kemudian, saat
        # step-nya sudah tidak bisa ditanya lagi — jadi pilihannya harus ikut
        # tersimpan di permintaan, bukan dibaca ulang nanti.
        self.jalankan_take_image(kamera="bawah_air")
        self.assertTrue(self.e.capture_pending)
        self.assertEqual(self.e._capture_kamera, MissionEngine.KAMERA_BAWAH_AIR)

    def test_pembatalan_memadamkan_pilihan_kamera(self):
        # Bendera shutter yang bocor sudah pernah jadi bug lapangan (lihat
        # tools/uji_kebocoran_shutter.py). Pilihan kameranya tidak boleh jadi
        # kebocoran kedua yang menumpang di belakangnya.
        self.jalankan_take_image(kamera="bawah_air")
        self.e.abort_mission()
        self.assertFalse(self.e.capture_pending)
        self.assertEqual(self.e._capture_kamera, "")


# ── Pemilihan sumber frame ──────────────────────────────────────────────────

class UjiSumberFoto(Dasar):
    def test_permintaan_bawah_air_memakai_kamera_bawah_air(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        frame, sumber, imbuhan = self.e._sumber_foto(
            FRAME_PERMUKAAN, "dermaga", MissionEngine.KAMERA_BAWAH_AIR)
        self.assertTrue(np.array_equal(frame, FRAME_BAWAH_AIR))
        self.assertEqual(sumber, "bawah air")
        self.assertEqual(imbuhan, "", "foto bawah air yang BERHASIL tidak diberi imbuhan")

    def test_kamera_tidak_terpasang_jatuh_ke_permukaan_dan_ditandai(self):
        self.e.set_underwater_camera(None)
        frame, sumber, imbuhan = self.e._sumber_foto(
            FRAME_PERMUKAAN, "dermaga", MissionEngine.KAMERA_BAWAH_AIR)
        self.assertTrue(np.array_equal(frame, FRAME_PERMUKAAN))
        self.assertEqual(imbuhan, "_permukaan")
        self.assertIn("tidak dipasang", sumber)

    def test_kamera_membeku_jatuh_ke_permukaan_dan_ditandai(self):
        # Terpasang tapi tidak memberi frame — kabel longgar, perangkat hilang.
        # Bedanya dari "tidak dipasang" harus terlihat di sumbernya: yang satu
        # pilihan operator, yang lain kerusakan.
        self.e.set_underwater_camera(KameraBawahAirPalsu(None))
        frame, sumber, imbuhan = self.e._sumber_foto(
            FRAME_PERMUKAAN, "dermaga", MissionEngine.KAMERA_BAWAH_AIR)
        self.assertTrue(np.array_equal(frame, FRAME_PERMUKAAN))
        self.assertEqual(imbuhan, "_permukaan")
        self.assertIn("cadangan", sumber)

    def test_meminta_permukaan_tidak_membajak_kamera_bawah_air(self):
        # Kamera bawah air ada dan sehat, tapi step ini memang minta permukaan.
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        frame, sumber, imbuhan = self.e._sumber_foto(
            FRAME_PERMUKAAN, "dermaga", MissionEngine.KAMERA_PERMUKAAN)
        self.assertTrue(np.array_equal(frame, FRAME_PERMUKAAN))
        self.assertEqual(sumber, "permukaan")
        self.assertEqual(imbuhan, "")

    def test_aturan_box_biru_tetap_berlaku_tanpa_permintaan(self):
        # Box biru bawah air karena ketentuan lomba, bukan karena operator
        # memilihnya — jadi tidak boleh ikut hilang saat pilihan ditambahkan.
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        frame, sumber, _ = self.e._sumber_foto(FRAME_PERMUKAAN, ROLE_BLUE_BOX, "")
        self.assertTrue(np.array_equal(frame, FRAME_BAWAH_AIR))
        self.assertEqual(sumber, "bawah air")

    def test_box_hijau_tetap_dari_permukaan(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        frame, sumber, _ = self.e._sumber_foto(FRAME_PERMUKAAN, ROLE_GREEN_BOX, "")
        self.assertTrue(np.array_equal(frame, FRAME_PERMUKAAN))
        self.assertEqual(sumber, "permukaan")


# ── Ujung ke ujung: berkas yang benar-benar tersimpan ───────────────────────

class UjiBerkasTersimpan(Dasar):
    def sidecar(self, path):
        with open(os.path.splitext(path)[0] + ".json", encoding="utf-8") as f:
            return json.load(f)

    def test_foto_bawah_air_menyimpan_piksel_kamera_bawah_air(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.jalankan_take_image(kamera="bawah_air")

        path = self.e.capture_now(FRAME_PERMUKAAN)
        self.assertIsNotNone(path, "foto harus tersimpan")
        self.buktikan_dari(path, "bawah air")

    def test_sidecar_mencatat_kamera_bawah_air(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.jalankan_take_image(kamera="bawah_air")
        path = self.e.capture_now(FRAME_PERMUKAAN)
        self.assertEqual(self.sidecar(path)["kamera"], "bawah air")

    def test_nama_berkas_bawah_air_TIDAK_diberi_imbuhan(self):
        # Backend mengambil label penilaian dari nama berkas. Imbuhan apa pun di
        # sini pernah membuat foto tersimpan tapi slotnya tampak kosong.
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.jalankan_take_image(kamera="bawah_air")
        path = self.e.capture_now(FRAME_PERMUKAAN)
        self.assertTrue(os.path.basename(path).endswith("_dermaga.jpg"),
                        f"nama tak terduga: {os.path.basename(path)}")

    def test_kejatuhan_ke_permukaan_terlihat_di_nama_berkas(self):
        # Inti seluruh berkas uji ini: foto permukaan TIDAK BOLEH bisa disangka
        # foto bawah air setelah lomba selesai.
        self.e.set_underwater_camera(None)
        self.jalankan_take_image(kamera="bawah_air")
        path = self.e.capture_now(FRAME_PERMUKAAN)
        self.assertTrue(os.path.basename(path).endswith("_permukaan.jpg"),
                        f"nama tak terduga: {os.path.basename(path)}")

    def test_kejatuhan_ke_permukaan_terlihat_di_sidecar(self):
        self.e.set_underwater_camera(None)
        self.jalankan_take_image(kamera="bawah_air")
        path = self.e.capture_now(FRAME_PERMUKAAN)
        self.assertIn("tidak dipasang", self.sidecar(path)["kamera"])

    def test_foto_permukaan_biasa_tetap_seperti_sebelumnya(self):
        self.jalankan_take_image()
        path = self.e.capture_now(FRAME_PERMUKAAN)
        self.assertTrue(os.path.basename(path).endswith("_dermaga.jpg"))
        self.assertEqual(self.sidecar(path)["kamera"], "permukaan")

    def test_shutter_hanya_dilayani_sekali(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.jalankan_take_image(kamera="bawah_air")
        self.assertIsNotNone(self.e.capture_now(FRAME_PERMUKAAN))
        self.assertIsNone(self.e.capture_now(FRAME_PERMUKAAN),
                          "permintaan yang sudah dilayani tidak boleh memotret lagi")


# ── Slot penilaian ──────────────────────────────────────────────────────────

class UjiSlotPenilaian(Dasar):
    """
    Label foto menentukan slot mana yang terisi di panel Foto Misi — backend
    menurunkannya dari nama berkas. Sebelum field "slot" ada, satu-satunya cara
    mengisi slot IMB adalah MENAMAI step-nya persis "blue_box", dan satu huruf
    besar saja sudah cukup untuk membuat fotonya mendarat di "Foto lain" dengan
    slot penilaian tetap kosong. Tidak ada error; yang hilang cuma nilainya.
    """

    def test_tanpa_slot_label_memakai_nama_step(self):
        self.jalankan_take_image()
        self.assertEqual(self.e._capture_label, "dermaga")

    def test_slot_imb_memakai_label_penilaian_bukan_nama_step(self):
        self.jalankan_take_image(slot="imb")
        self.assertEqual(self.e._capture_label, ROLE_BLUE_BOX)

    def test_slot_imh_memakai_label_box_hijau(self):
        self.jalankan_take_image(slot="imh")
        self.assertEqual(self.e._capture_label, ROLE_GREEN_BOX)

    def test_slot_salah_ketik_tidak_diam_diam_mengisi_slot(self):
        # Foto yang menumpuk di slot penilaian tanpa diniatkan akan MENIMPA
        # tampilan foto yang sah.
        self.jalankan_take_image(slot="ngawurr")
        self.assertEqual(self.e._capture_label, "dermaga")

    def test_slot_imb_memaksa_kamera_bawah_air_walau_operator_pilih_permukaan(self):
        # Box biru adalah target bawah air menurut ketentuan lomba, bukan
        # preferensi yang boleh ditawar. Foto permukaan yang mengisi slot IMB
        # adalah bukti palsu — persis yang seluruh berkas ini ada untuk mencegah.
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.jalankan_take_image(slot="imb", kamera="permukaan")

        path = self.e.capture_now(FRAME_PERMUKAAN)
        self.buktikan_dari(path, "bawah air")

    def test_slot_imb_menghasilkan_nama_berkas_yang_mengisi_slot(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.jalankan_take_image(slot="imb")
        path = self.e.capture_now(FRAME_PERMUKAAN)
        # Backend mengambil label dari nama berkas: ..._blue_box → "blue_box",
        # yang cocok dengan slot Underwater di dashboard.
        self.assertTrue(os.path.basename(path).endswith("_blue_box.jpg"),
                        f"nama tak terduga: {os.path.basename(path)}")

    def test_kamera_gagal_TIDAK_boleh_mengisi_slot_imb(self):
        # Kejatuhan ke permukaan memberi akhiran "_permukaan", sehingga labelnya
        # jadi "blue_box_permukaan" dan TIDAK cocok dengan slot Underwater. Itu
        # disengaja: kalau foto bawah air tidak pernah terjadi, slot penilaian
        # MEMANG harus kosong, bukan diisi foto permukaan yang menyamar.
        self.e.set_underwater_camera(None)
        self.jalankan_take_image(slot="imb")
        path = self.e.capture_now(FRAME_PERMUKAAN)
        self.assertTrue(os.path.basename(path).endswith("_blue_box_permukaan.jpg"),
                        f"nama tak terduga: {os.path.basename(path)}")

    def test_slot_imh_dengan_bawaan_memakai_kamera_permukaan(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        self.jalankan_take_image(slot="imh")
        path = self.e.capture_now(FRAME_PERMUKAAN)
        self.buktikan_dari(path, "permukaan")
        self.assertTrue(os.path.basename(path).endswith("_green_box.jpg"))


class UjiPresedensiKamera(Dasar):
    """
    Urutan kewenangan pemilihan kamera, dan bukti bahwa step LAIN tidak berubah.
    """

    def test_step_tanpa_permintaan_tetap_mengikuti_aturan_label(self):
        # Inilah jalur PHOTO_BOX, BOX_CHANNEL, dan BOX_APPROACH. Mereka tidak
        # pernah mengisi pilihan kamera, jadi harus melewati jalur yang identik
        # dengan sebelum field "kamera" ada sama sekali.
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))

        frame, sumber, _ = self.e._sumber_foto(FRAME_PERMUKAAN, ROLE_BLUE_BOX, "")
        self.assertTrue(np.array_equal(frame, FRAME_BAWAH_AIR))
        self.assertEqual(sumber, "bawah air")

        frame, sumber, _ = self.e._sumber_foto(FRAME_PERMUKAAN, ROLE_GREEN_BOX, "")
        self.assertTrue(np.array_equal(frame, FRAME_PERMUKAAN))
        self.assertEqual(sumber, "permukaan")

    def test_label_box_biru_mengalahkan_permintaan_permukaan(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        frame, _, _ = self.e._sumber_foto(
            FRAME_PERMUKAAN, ROLE_BLUE_BOX, MissionEngine.KAMERA_PERMUKAAN)
        self.assertTrue(np.array_equal(frame, FRAME_BAWAH_AIR),
                        "ketentuan lomba harus menang atas pilihan operator")

    def test_permintaan_berlaku_untuk_label_yang_bukan_slot_penilaian(self):
        self.e.set_underwater_camera(KameraBawahAirPalsu(FRAME_BAWAH_AIR))
        frame, _, _ = self.e._sumber_foto(
            FRAME_PERMUKAAN, "dermaga", MissionEngine.KAMERA_BAWAH_AIR)
        self.assertTrue(np.array_equal(frame, FRAME_BAWAH_AIR))


if __name__ == "__main__":
    unittest.main(verbosity=2)
