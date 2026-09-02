"""
Uji perilaku step BOX_APPROACH tanpa kapal, kamera, atau flight controller.

Jalankan:  python3 tools/uji_box_approach.py

Yang diuji adalah hal-hal yang TIDAK terlihat dari membaca kode dan mahal
dibuktikan di danau: apakah kapal benar-benar berpindah fase pada saat yang
tepat, apakah pengaman tabrakan menyala saat box tidak pernah terpusat, dan
apakah step selalu punya jalan untuk selesai. Tiga hal itu masing-masing pernah
jadi bug nyata di step lain dalam proyek ini.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control.mission_engine import MissionEngine
from vision.class_map import ROLE_BLUE_BOX, ROLE_GREEN_BOX

LEBAR, TINGGI = 1920, 1080


class AsvPalsu:
    """Kapal palsu: cukup untuk membuat engine merasa terhubung dan di MANUAL."""

    class _Telemetry:
        mode = "MANUAL"

    def is_connected(self):
        return True

    def get_telemetry(self):
        return self._Telemetry()

    def set_mode(self, mode):
        return True

    def stop_movement(self, silent=False):
        return True


class KontrolerPalsu:
    def reset(self):
        pass


def box(cx, luas, tinggi_rasio=1.0):
    """Bikin tuple deteksi (cx, cy, x1, y1, x2, y2) dengan luas yang diminta."""
    lebar = (luas / tinggi_rasio) ** 0.5
    tinggi = lebar * tinggi_rasio
    return (cx, TINGGI / 2, cx - lebar / 2, TINGGI / 2 - tinggi / 2,
            cx + lebar / 2, TINGGI / 2 + tinggi / 2)


class BasisUji:
    """Helper bersama. Bukan TestCase supaya uji-nya tidak ikut jalan dua kali."""

    def setUp(self):
        self.engine = MissionEngine(AsvPalsu(), None, KontrolerPalsu(),
                                    camera_width=LEBAR, camera_height=TINGGI)

    def jalankan(self, step, boxes=None, frame_ke=1):
        """Panggil update_frame sekali dengan deteksi yang diberikan."""
        return self.engine.update_frame(None, None, {"red": [], "green": []},
                                        boxes if boxes is not None else {})

    def mulai(self, **field):
        step = {"type": "BOX_APPROACH"}
        step.update(field)
        self.engine.load_mission([step, {"type": "FINISH"}])
        self.engine.start_mission()
        return step


class UjiBoxApproach(BasisUji, unittest.TestCase):

    # ── Fase SCAN ──────────────────────────────────────────────────────────

    def test_scan_memakai_throttle_dan_arah_sapuan_sendiri(self):
        """Tanpa box, kapal menyapu memakai nilai SCAN — bukan nilai APPROACH."""
        self.mulai(scan_throttle=0.4, scan_steer=-0.3, approach_throttle=0.9)
        steer, thr, label = self.jalankan(None, {})
        self.assertAlmostEqual(steer, -0.3, places=6, msg="arah sapuan harus ke kiri")
        self.assertAlmostEqual(thr, 0.4, places=6, msg="harus pakai scan_throttle")
        self.assertIn("SCAN", label)

    def test_scan_menyerah_dan_step_selesai(self):
        """Box tak pernah ketemu: step SELESAI, tidak menggantung selamanya."""
        self.mulai(scan_timeout_sec=0.2)
        self.jalankan(None, {})
        time.sleep(0.25)
        steer, thr, _ = self.jalankan(None, {})
        self.assertEqual(steer, 0.0)
        self.assertEqual(thr, 0.0)
        self.assertGreater(self.engine.get_status_dict()["current_step_idx"], 0,
                           "step harus sudah lanjut, bukan mengulang SCAN")

    def test_box_terlalu_kecil_diabaikan(self):
        """Bbox di bawah ambang deteksi tidak boleh mengunci kapal ke sasaran palsu."""
        self.mulai(min_detect_area_px2=5000, scan_steer=0.25)
        _, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 900)]})
        self.assertIn("SCAN", label, "pantulan kecil seharusnya tetap dianggap tidak ada box")

    def test_warna_lain_tidak_memicu_apa_apa(self):
        """Step yang mencari biru tidak boleh bereaksi pada box hijau."""
        self.mulai(target="blue")
        _, _, label = self.jalankan(None, {ROLE_GREEN_BOX: [box(LEBAR / 2, 60000)]})
        self.assertIn("SCAN", label)

    # ── Fase APPROACH ──────────────────────────────────────────────────────

    def test_approach_membelok_ke_arah_box(self):
        """Box di KANAN frame → kemudi POSITIF (kanan). Tanda ini pernah kebalik."""
        self.mulai(target_area_px2=200000)
        steer, thr, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR * 0.8, 20000)]})
        self.assertGreater(steer, 0.0, "box di kanan harus membuat kapal belok kanan")
        self.assertIn("APPROACH", label)

        self.setUp()
        self.mulai(target_area_px2=200000)
        steer, _, _ = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR * 0.2, 20000)]})
        self.assertLess(steer, 0.0, "box di kiri harus membuat kapal belok kiri")

    def test_batas_kemudi_dihormati(self):
        """Gain besar tidak boleh berubah jadi bantingan penuh."""
        self.mulai(target_area_px2=200000, approach_steer_gain=10.0, max_steer=0.3)
        steer, _, _ = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR * 0.95, 20000)]})
        self.assertLessEqual(abs(steer), 0.3 + 1e-9)

    def test_approach_memakai_throttlenya_sendiri(self):
        self.mulai(target_area_px2=200000, approach_throttle=0.42, scan_throttle=0.1)
        _, thr, _ = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2 + 300, 20000)]})
        self.assertAlmostEqual(thr, 0.42, places=6)

    def test_kedip_deteksi_tidak_meluruskan_haluan(self):
        """Box hilang satu frame: kemudi terakhir dipertahankan, bukan direset ke sapuan."""
        self.mulai(target_area_px2=200000, lost_grace_sec=5.0, scan_steer=0.0)
        steer_awal, _, _ = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR * 0.8, 20000)]})
        steer_hilang, _, label = self.jalankan(None, {})
        self.assertAlmostEqual(steer_hilang, steer_awal, places=6)
        self.assertIn("hilang sekejap", label)

    def test_box_hilang_lama_kembali_mencari(self):
        self.mulai(target_area_px2=200000, lost_grace_sec=0.1, scan_steer=0.2)
        self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR * 0.8, 20000)]})
        time.sleep(0.15)
        steer, _, label = self.jalankan(None, {})
        self.assertIn("SCAN", label)
        self.assertAlmostEqual(steer, 0.2, places=6)

    # ── Pemicu menghindar ──────────────────────────────────────────────────

    def test_menghindar_butuh_DUA_syarat(self):
        """Di tengah tapi masih jauh → belum menghindar. Dekat tapi tidak di tengah → belum."""
        self.mulai(target_area_px2=50000, center_tolerance_px=100,
                   force_evade_area_ratio=0)  # pengaman dimatikan agar syaratnya murni

        _, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 10000)]})
        self.assertIn("APPROACH", label, "di tengah tapi masih jauh: belum boleh menghindar")

        self.setUp()
        self.mulai(target_area_px2=50000, center_tolerance_px=100, force_evade_area_ratio=0)
        _, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2 + 400, 60000)]})
        self.assertIn("APPROACH", label, "dekat tapi tidak di tengah: belum boleh menghindar")

    def test_dua_syarat_terpenuhi_langsung_menghindar(self):
        self.mulai(target_area_px2=50000, center_tolerance_px=100, evade_sec=5.0)
        steer, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        self.assertIn("EVADE", label)
        self.assertLess(steer, 0.0, "default arah menghindar adalah KIRI")

    def test_pengaman_tabrakan_menyala_saat_tak_pernah_terpusat(self):
        """
        Ini alasan utama pengaman itu ada: box yang tidak pernah masuk toleransi
        tengah akan membuat kapal mendekat terus tanpa pernah memenuhi syarat.
        """
        self.mulai(target_area_px2=50000, center_tolerance_px=5,
                   force_evade_area_ratio=1.5, evade_sec=5.0)
        _, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR * 0.9, 60000)]})
        self.assertIn("APPROACH", label, "1.2x target: belum waktunya pengaman menyala")

        _, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR * 0.9, 80000)]})
        self.assertIn("EVADE", label, "1.6x target: pengaman WAJIB menyala")
        self.assertIn("PENGAMAN", self.engine.get_status_dict()["bap_evade_reason"])

    def test_pengaman_bisa_dimatikan(self):
        self.mulai(target_area_px2=50000, center_tolerance_px=5, force_evade_area_ratio=0)
        _, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR * 0.9, 500000)]})
        self.assertIn("APPROACH", label)

    # ── Fase EVADE ─────────────────────────────────────────────────────────

    def test_arah_menghindar_bisa_diatur(self):
        for arah, tanda in (("kanan", 1), ("right", 1), ("kiri", -1), ("left", -1)):
            with self.subTest(arah=arah):
                self.setUp()
                self.mulai(target_area_px2=50000, evade_direction=arah,
                           evade_steer=0.6, evade_sec=5.0)
                steer, _, _ = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
                self.assertAlmostEqual(steer, tanda * 0.6, places=6)

    def test_arah_auto_mengikuti_warna_box(self):
        """Biru menandai tepi kanan → menghindar ke KIRI. Hijau sebaliknya."""
        self.mulai(target="blue", target_area_px2=50000, evade_direction="auto",
                   evade_steer=0.5, evade_sec=5.0)
        steer, _, _ = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        self.assertLess(steer, 0.0)

        self.setUp()
        self.mulai(target="green", target_area_px2=50000, evade_direction="auto",
                   evade_steer=0.5, evade_sec=5.0)
        steer, _, _ = self.jalankan(None, {ROLE_GREEN_BOX: [box(LEBAR / 2, 60000)]})
        self.assertGreater(steer, 0.0)

    def test_arah_salah_ketik_jatuh_ke_default_aman(self):
        self.mulai(target_area_px2=50000, evade_direction="kirii", evade_sec=5.0)
        steer, _, _ = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        self.assertLess(steer, 0.0, "salah ketik tidak boleh diam-diam jadi KANAN")

    def test_menghindar_tetap_jalan_walau_box_hilang(self):
        """Begitu kapal membanting, box keluar frame. Manuver TIDAK boleh terpotong."""
        self.mulai(target_area_px2=50000, evade_steer=0.5, evade_throttle=0.35,
                   evade_sec=5.0)
        self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        steer, thr, label = self.jalankan(None, {})
        self.assertIn("EVADE", label)
        self.assertAlmostEqual(steer, -0.5, places=6)
        self.assertAlmostEqual(thr, 0.35, places=6)

    def test_step_selesai_setelah_durasi_menghindar(self):
        self.mulai(target_area_px2=50000, evade_sec=0.2)
        self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        time.sleep(0.25)
        steer, thr, _ = self.jalankan(None, {})
        self.assertEqual((steer, thr), (0.0, 0.0))
        self.assertGreater(self.engine.get_status_dict()["current_step_idx"], 0)

    # ── Pengaman umum ──────────────────────────────────────────────────────

    def test_batas_keras_seluruh_step(self):
        """Deteksi berkedip me-reset batas SCAN — batas keras yang menutup celah itu."""
        self.mulai(target_area_px2=500000, max_duration_sec=0.3, scan_timeout_sec=999)
        for _ in range(3):
            self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 20000)]})
            self.jalankan(None, {})
        time.sleep(0.35)
        self.jalankan(None, {})
        self.assertGreater(self.engine.get_status_dict()["current_step_idx"], 0,
                           "batas keras harus menyelesaikan step apa pun fasenya")

    def test_field_kosong_tidak_bikin_crash(self):
        """
        Input number di panel bisa dikosongkan operator sebelum misi diunggah.
        float('') melempar ValueError, dan exception di jalur ini pernah mematikan
        seluruh thread streaming+kontrol.
        """
        self.mulai(scan_throttle="", scan_steer="", approach_throttle=None,
                   target_area_px2="", evade_sec="abc", evade_direction="",
                   max_steer="", force_evade_area_ratio="")
        for boxes in ({}, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]}, {}):
            steer, thr, _ = self.jalankan(None, boxes)
            self.assertTrue(-1.0 <= steer <= 1.0, f"steer di luar batas: {steer}")
            self.assertTrue(0.0 <= thr <= 1.0, f"throttle di luar batas: {thr}")

    def test_semua_keluaran_selalu_dalam_batas_aman(self):
        """Nilai ekstrem dari panel tidak boleh lolos jadi perintah RC di luar rentang."""
        self.mulai(scan_throttle=9.0, scan_steer=-9.0, approach_throttle=9.0,
                   approach_steer_gain=99.0, max_steer=9.0, evade_throttle=9.0,
                   evade_steer=9.0, evade_sec=5.0, target_area_px2=50000)
        kasus = [{}, {ROLE_BLUE_BOX: [box(LEBAR * 0.99, 20000)]},
                 {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]}, {}]
        for boxes in kasus:
            steer, thr, _ = self.jalankan(None, boxes)
            self.assertTrue(-1.0 <= steer <= 1.0, f"steer di luar batas: {steer}")
            self.assertTrue(0.0 <= thr <= 1.0, f"throttle di luar batas: {thr}")


class UjiBoxApproachFoto(BasisUji, unittest.TestCase):
    """
    Fase SHOOT — opsional, default MATI.

    main.py-lah yang benar-benar memotret: engine cuma menyalakan capture_pending
    dan menunggu bendera itu turun. Di sini main.py disimulasikan dengan menurunkan
    benderanya sendiri, jadi yang diuji adalah KONTRAKNYA, bukan kameranya.
    """

    def layani_shutter(self):
        """Perankan main.py: ambil fotonya."""
        self.assertTrue(self.engine.capture_pending, "engine belum meminta shutter")
        self.engine._capture_pending = False

    def test_default_tidak_pernah_memotret(self):
        """Tanpa field photo, step ini murni manuver — persis seperti sebelum fitur foto."""
        self.mulai(target_area_px2=50000, evade_sec=5.0)
        _, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        self.assertIn("EVADE", label, "default harus langsung menghindar, tanpa SHOOT")
        self.assertFalse(self.engine.capture_pending)

    def test_salah_ketik_dianggap_tidak_memotret(self):
        self.mulai(target_area_px2=50000, photo="stopp", evade_sec=5.0)
        _, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        self.assertIn("EVADE", label)
        self.assertFalse(self.engine.capture_pending)

    def test_mode_moving_menjepret_tanpa_berhenti(self):
        self.mulai(target_area_px2=50000, photo="moving", approach_throttle=0.3,
                   evade_sec=5.0)
        steer, thr, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        self.assertIn("SHOOT", label)
        self.assertTrue(self.engine.capture_pending)
        self.assertAlmostEqual(thr, 0.3, places=6, msg="mode moving tidak boleh berhenti")

        self.layani_shutter()
        steer, _, label = self.jalankan(None, {})
        self.assertIn("EVADE", label)
        self.assertLess(steer, 0.0)

    def test_mode_stop_diam_dulu_baru_jepret(self):
        self.mulai(target_area_px2=50000, photo="stop", photo_settle_sec=0.3,
                   evade_sec=5.0)
        steer, thr, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        self.assertIn("SETTLE", label)
        self.assertEqual((steer, thr), (0.0, 0.0), "mode stop harus benar-benar berhenti")
        self.assertFalse(self.engine.capture_pending, "shutter jangan diminta sebelum diam")

        time.sleep(0.35)
        _, _, label = self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        self.assertIn("SHOOT", label)
        self.assertTrue(self.engine.capture_pending)

        self.layani_shutter()
        _, _, label = self.jalankan(None, {})
        self.assertIn("EVADE", label)

    def test_shutter_tidak_dibatalkan_saat_deteksi_berkedip(self):
        """Box hilang setelah shutter diminta: permintaannya tidak boleh hangus."""
        self.mulai(target_area_px2=50000, photo="moving", evade_sec=5.0)
        self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        _, _, label = self.jalankan(None, {})
        self.assertIn("SHOOT", label)
        self.assertTrue(self.engine.capture_pending)

    def test_kamera_mati_tetap_menghindar(self):
        """
        Frame bersih tidak pernah datang. Kapal sudah terlanjur mengarah ke box —
        kamera yang gagal bukan alasan untuk menabraknya.
        """
        self.mulai(target_area_px2=50000, photo="moving", evade_sec=5.0)
        self.engine.BAP_SHOOT_TIMEOUT_SEC = 0.2
        self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        time.sleep(0.25)
        steer, _, label = self.jalankan(None, {})
        self.assertIn("EVADE", label)
        self.assertLess(steer, 0.0)
        self.assertFalse(self.engine.capture_pending, "permintaan shutter harus dibatalkan")

    def test_batas_keras_tidak_mewariskan_shutter(self):
        """Step yang dipotong batas waktu tidak boleh membuat step berikutnya memotret."""
        self.mulai(target_area_px2=50000, photo="stop", photo_settle_sec=99,
                   max_duration_sec=0.3)
        self.jalankan(None, {ROLE_BLUE_BOX: [box(LEBAR / 2, 60000)]})
        time.sleep(0.35)
        self.jalankan(None, {})
        self.assertFalse(self.engine.capture_pending,
                         "shutter menggantung akan memotret di momen yang tidak diminta")

    def test_label_foto_ikut_warna_box(self):
        self.mulai(target="green", target_area_px2=50000, photo="moving", evade_sec=5.0)
        self.jalankan(None, {ROLE_GREEN_BOX: [box(LEBAR / 2, 60000)]})
        self.assertEqual(self.engine._capture_label, ROLE_GREEN_BOX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
