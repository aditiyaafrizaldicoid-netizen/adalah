"""
Uji serah-terima kendali: remote mengambil alih = misi BERHENTI.

Jalankan:  python3 tools/uji_serah_kendali.py

BUG LAPANGAN yang ditutup berkas ini: memindahkan sumber kendali ke remote dulu
hanya menutup gerbang perintah gerak. Mesin misi TIDAK ikut berhenti — state
machine-nya terus jalan, step-stepnya tetap kedaluwarsa dan berpindah sendiri,
dan dashboard tetap menampilkan "RUNNING" beserta kemajuan langkahnya. Operator
memegang kapal lewat remote sementara misi diam-diam terus berjalan, lalu saat
kendali dikembalikan misinya sudah berada di langkah yang tidak diharapkan.

Tidak ada error, tidak ada log — cuma dua sistem yang mengira dirinya memegang
kapal.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control import manual_source
from core.client import ASVController


class MotionPalsu:
    def __init__(self):
        self.dilepas = 0

    def release_all_rc(self, verbose=False):
        self.dilepas += 1
        return True


class MisiPalsu:
    def __init__(self, status="RUNNING"):
        self.status = status
        self.dibatalkan = 0

    def abort_mission(self):
        self.dibatalkan += 1
        self.status = "ABORTED"


class TelemetriPalsu:
    def __init__(self, mode):
        self.mode = mode


def kontroler(mode="MANUAL", set_mode_ok=True):
    """ASVController tanpa koneksi MAVLink — hanya bagian sumber kendali."""
    import threading
    a = ASVController.__new__(ASVController)
    a._manual_source = manual_source.MINIPC
    a._manual_source_lock = threading.RLock()
    a._remote_block_last_log = 0.0
    a._on_manual_source_change = None
    a._motion = MotionPalsu()
    # Pelepasan diulang beberapa kali dengan jeda; untuk uji cukup sekali.
    a.RELEASE_REPEAT = 1
    a.RELEASE_INTERVAL_SEC = 0

    a._mode_fc = mode
    a.mode_diminta = []

    def _get_telemetry():
        return TelemetriPalsu(a._mode_fc)

    def _set_mode(m):
        a.mode_diminta.append(m)
        if set_mode_ok:
            a._mode_fc = m
        return set_mode_ok

    a.get_telemetry = _get_telemetry
    a.set_mode = _set_mode
    return a


class UjiSerahKendali(unittest.TestCase):

    def setUp(self):
        self.asv = kontroler()
        self.misi = MisiPalsu()
        self.peringatan = []

        def pada_pindah(sebelum, sekarang):
            if sekarang != manual_source.REMOTE:
                return
            if self.misi.status == "RUNNING":
                self.misi.abort_mission()
                self.peringatan.append("MISI_DIHENTIKAN_REMOTE")

        self.asv.set_manual_source_callback(pada_pindah)

    # ── Inti perbaikan ────────────────────────────────────────────────────

    def test_remote_mengambil_alih_menghentikan_misi(self):
        self.asv.set_manual_source("remote")
        self.assertEqual(self.misi.status, "ABORTED")
        self.assertEqual(self.misi.dibatalkan, 1)
        self.assertEqual(self.peringatan, ["MISI_DIHENTIKAN_REMOTE"])

    def test_dashboard_diberi_tahu_alasannya(self):
        """Misi yang berhenti tanpa keterangan terbaca sebagai kapal yang rusak."""
        self.asv.set_manual_source("remote")
        self.assertIn("MISI_DIHENTIKAN_REMOTE", self.peringatan)

    def test_kembali_ke_minipc_TIDAK_melanjutkan_misi(self):
        """
        Misi yang hidup lagi tanpa diminta adalah kapal yang tiba-tiba bergerak
        saat operator mengira sedang memegang kendali.
        """
        self.asv.set_manual_source("remote")
        self.asv.set_manual_source("minipc")
        self.assertEqual(self.misi.status, "ABORTED")
        self.assertEqual(self.misi.dibatalkan, 1)

    def test_tanpa_misi_berjalan_tidak_ada_yang_dibatalkan(self):
        self.misi.status = "IDLE"
        self.asv.set_manual_source("remote")
        self.assertEqual(self.misi.dibatalkan, 0)
        self.assertEqual(self.peringatan, [])

    # ── Ketahanan corong ──────────────────────────────────────────────────

    def test_callback_hanya_dipanggil_saat_benar_benar_berpindah(self):
        panggil = []
        self.asv.set_manual_source_callback(lambda a, b: panggil.append((a, b)))
        self.asv.set_manual_source("minipc")     # sudah minipc — bukan perpindahan
        self.assertEqual(panggil, [])
        self.asv.set_manual_source("remote")
        self.asv.set_manual_source("remote")     # sudah remote
        self.assertEqual(panggil, [(manual_source.MINIPC, manual_source.REMOTE)])

    def test_sumber_tidak_dikenal_tidak_memicu_apa_pun(self):
        panggil = []
        self.asv.set_manual_source_callback(lambda a, b: panggil.append((a, b)))
        self.assertFalse(self.asv.set_manual_source("entah"))
        self.assertEqual(panggil, [])
        self.assertEqual(self.asv.get_manual_source(), manual_source.MINIPC)

    def test_callback_yang_error_tidak_membatalkan_perpindahan(self):
        """
        Saat callback jalan, gerbang sudah tertutup dan override sudah dilepas —
        remote SUDAH memegang kapal. Melempar dari sini hanya meninggalkan sistem
        setengah jalan.
        """
        self.asv.set_manual_source_callback(
            lambda a, b: (_ for _ in ()).throw(RuntimeError("meledak")))
        self.assertTrue(self.asv.set_manual_source("remote"))
        self.assertEqual(self.asv.get_manual_source(), manual_source.REMOTE)

    def test_gerbang_ditutup_SEBELUM_callback_jalan(self):
        """
        Callback menghentikan misi, dan abort_mission() memanggil stop_movement().
        Kalau gerbangnya belum tertutup saat itu, perintah stop tersebut justru
        merebut kembali override dari remote yang baru saja diserahi kendali.
        """
        terlihat = []
        self.asv.set_manual_source_callback(
            lambda a, b: terlihat.append(self.asv.minipc_has_control()))
        self.asv.set_manual_source("remote")
        self.assertEqual(terlihat, [False], "gerbang masih terbuka saat callback jalan")

    # ── Kedua jalur perpindahan bermuara ke sini ──────────────────────────

    def test_sakelar_remote_memakai_corong_yang_sama(self):
        """
        Sumber kendali bisa berpindah dari dua arah: sakelar fisik di remote dan
        tombol dashboard. Keduanya HARUS lewat set_manual_source(), kalau tidak
        salah satunya luput dari penghentian misi.
        """
        import inspect
        from control import rc_source_switch
        self.assertIn("set_manual_source", inspect.getsource(rc_source_switch))

    def test_perintah_dashboard_memakai_corong_yang_sama(self):
        import inspect
        from connection import websocket
        sumber = inspect.getsource(websocket.ASVWebSocketClient._handle_set_manual_source)
        self.assertIn("set_manual_source", sumber)


class UjiPemulihanMode(unittest.TestCase):
    """
    Melepaskan override RC saja TIDAK cukup membuat kapal menurut.

    Kalau flight controller tertinggal di mode otonom (GUIDED — dan misi memang
    menyetelnya ke sana), tidak ada masukan tangan yang menggerakkan rover:
    stik remote diam, joystick dashboard diam. Tampak persis seperti kapal rusak,
    tanpa satu pun error.
    """

    def test_ke_remote_dari_GUIDED_mode_dipulihkan(self):
        a = kontroler(mode="GUIDED")
        a.set_manual_source("remote")
        self.assertEqual(a.mode_diminta, ["MANUAL"])
        self.assertEqual(a._mode_fc, "MANUAL")

    def test_ke_MINIPC_dari_GUIDED_juga_dipulihkan(self):
        """Joystick dashboard sama tidak berfungsinya di GUIDED."""
        a = kontroler(mode="GUIDED")
        a.set_manual_source("remote")
        a.mode_diminta.clear()
        a._mode_fc = "GUIDED"          # misal misi menyetelnya lagi
        a.set_manual_source("minipc")
        self.assertEqual(a.mode_diminta, ["MANUAL"])

    def test_mode_yang_SUDAH_bisa_distik_tidak_diganggu(self):
        """Operator yang sengaja memilih ACRO/STEERING jangan dipaksa ke MANUAL."""
        for mode in ("MANUAL", "ACRO", "STEERING", "HOLD"):
            with self.subTest(mode=mode):
                a = kontroler(mode=mode)
                a.set_manual_source("remote")
                self.assertEqual(a.mode_diminta, [], f"{mode} tidak perlu diubah")
                self.assertEqual(a._mode_fc, mode)

    def test_semua_mode_otonom_dipulihkan(self):
        for mode in ("GUIDED", "AUTO", "RTL", "SMART_RTL", "LOITER", "FOLLOW"):
            with self.subTest(mode=mode):
                a = kontroler(mode=mode)
                a.set_manual_source("remote")
                self.assertEqual(a.mode_diminta, ["MANUAL"])

    def test_mode_dipulihkan_SEBELUM_override_dilepas(self):
        """
        Mengganti mode selagi override masih aktif membuat kapal tetap dikemudikan
        mini PC selama peralihan — bukan sesaat tidak dikemudikan siapa pun.
        """
        a = kontroler(mode="GUIDED")
        urutan = []
        set_mode_asli = a.set_mode
        a.set_mode = lambda m: (urutan.append("mode"), set_mode_asli(m))[1]
        rilis_asli = a._motion.release_all_rc
        a._motion.release_all_rc = lambda verbose=False: (urutan.append("rilis"),
                                                          rilis_asli(verbose))[1]
        a.set_manual_source("remote")
        self.assertEqual(urutan, ["mode", "rilis"])

    def test_set_mode_gagal_tidak_membatalkan_perpindahan(self):
        """Gerbang sudah tertutup; membatalkan di sini meninggalkan keadaan separuh."""
        a = kontroler(mode="GUIDED", set_mode_ok=False)
        self.assertTrue(a.set_manual_source("remote"))
        self.assertEqual(a.get_manual_source(), manual_source.REMOTE)

    def test_telemetri_tak_terbaca_tidak_bikin_crash(self):
        a = kontroler(mode="GUIDED")
        def _meledak():
            raise RuntimeError("FC putus")
        a.get_telemetry = _meledak
        self.assertTrue(a.set_manual_source("remote"))
        self.assertEqual(a.get_manual_source(), manual_source.REMOTE)

    def test_satu_tabel_dipakai_kedua_modul(self):
        """
        Daftar mode hidup di control/manual_source.py. Dua daftar terpisah —
        satu untuk memulihkan, satu untuk menolak — pasti melenceng cepat atau
        lambat, dan melencengnya tidak menimbulkan error.
        """
        import inspect
        from connection import websocket
        sumber = inspect.getsource(websocket)
        self.assertIn("bisa_dikemudikan_remote", sumber)
        self.assertFalse(hasattr(websocket.ASVWebSocketClient, "MODE_OTONOM"),
                         "daftar mode duplikat muncul lagi")


if __name__ == "__main__":
    unittest.main(verbosity=2)
