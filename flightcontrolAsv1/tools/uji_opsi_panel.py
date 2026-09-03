"""
Uji silang: setiap pilihan di dropdown panel misi harus BERARTI SAMA di kapal.

Jalankan:  python3 tools/uji_opsi_panel.py

Field seperti "Mode Pemotretan" atau "Arah Menghindar" dulu berupa teks bebas,
dan salah ketik di situ tidak pernah memunculkan error: parser di
mission_engine.py diam-diam jatuh ke perilaku default, lalu kapal menjalankan
manuver yang sama sekali lain dari yang dimaksud operator. Dropdown menutup
jalur itu — TAPI cuma kalau daftar pilihannya benar-benar cocok dengan parser.

Daftar itu hidup di dua bahasa dan dua berkas yang berjauhan:

    frontend/src/stores/missionStore.js   ← yang DILIHAT operator
    flightcontrolAsv1/control/mission_engine.py  ← yang DIKERJAKAN kapal

Berkas ini membaca daftar yang sebenarnya dari berkas JS-nya, lalu menjalankan
tiap nilai dan tiap aliasnya melewati parser Python yang sesungguhnya. Menuliskan
ulang daftarnya di sini tidak ada gunanya — yang perlu dibuktikan justru bahwa
kedua berkas itu tidak pernah menyimpang.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control.mission_engine import MissionEngine
from vision.class_map import ROLE_BLUE_BOX, ROLE_GREEN_BOX

AKAR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE = os.path.join(AKAR, "frontend", "src", "stores", "missionStore.js")

# Node dipakai untuk MEMBACA daftarnya, bukan untuk menjalankan apa pun. Kalau
# tidak ada (mis. di Mini PC yang cuma menjalankan Python), test-nya di-skip.
SKRIP_NODE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const m = src.indexOf('const STEP_TYPES');
const b = src.indexOf('[', m);
let d = 0, i = b;
for (; i < src.length; i++) {
  if (src[i] === '[') d++;
  else if (src[i] === ']') { d--; if (d === 0) break; }
}
process.stdout.write(JSON.stringify(eval(src.slice(b, i + 1))));
"""


def baca_step_types():
    if not os.path.exists(STORE):
        raise unittest.SkipTest(f"missionStore.js tidak ada di {STORE}")
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node tidak terpasang — tidak bisa membaca daftar opsi")
    hasil = subprocess.run([node, "-e", SKRIP_NODE, STORE],
                           capture_output=True, text=True, timeout=60)
    if hasil.returncode != 0:
        raise AssertionError(f"gagal membaca STEP_TYPES: {hasil.stderr.strip()}")
    return json.loads(hasil.stdout)


def field_select():
    """[(tipe_step, field), ...] untuk semua field dropdown di panel."""
    keluar = []
    for step in baca_step_types():
        for f in step.get("fields", []):
            if f.get("type") == "select":
                keluar.append((step["type"], f))
    return keluar


SKRIP_NILAI_TERPILIH = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
// Ambil nilaiTerpilih() YANG SESUNGGUHNYA dari berkas store, bukan salinannya.
const awal = src.indexOf('export const nilaiTerpilih');
if (awal < 0) { console.error('nilaiTerpilih tidak ditemukan di store'); process.exit(2); }
const akhir = src.indexOf('\n};', awal);
const fn = eval('(' + src.slice(src.indexOf('=', awal) + 1, akhir + 2) + ')');
const { field, ejaan } = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(
  ejaan.map((v) => fn({ [field.key]: v }, field))
));
"""


def jalankan_nilai_terpilih(field, ejaan):
    """Jalankan nilaiTerpilih() milik frontend untuk sederet nilai mentah."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node tidak terpasang")
    muatan = json.dumps({"field": field, "ejaan": ejaan})
    hasil = subprocess.run([node, "-e", SKRIP_NILAI_TERPILIH, STORE, muatan],
                           capture_output=True, text=True, timeout=60)
    if hasil.returncode != 0:
        raise AssertionError(f"nilaiTerpilih gagal dijalankan: {hasil.stderr.strip()}")
    return json.loads(hasil.stdout)


class UjiOpsiPanel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.fields = field_select()
        if not cls.fields:
            raise AssertionError("tidak ada field select sama sekali — panel salah baca")

    def setUp(self):
        self.engine = MissionEngine.__new__(MissionEngine)

    # ── MAKNA: nilai apa pun → perilaku kapal yang sebenarnya ──────────────
    #
    # Untuk arah menghindar, maknanya diambil dari KEDUA warna box sekaligus:
    # "auto" kebetulan sama dengan "kiri" untuk box biru, dan cuma terlihat
    # berbeda saat box hijau. Menilainya dari satu warna saja akan menyimpulkan
    # dua pilihan yang berbeda itu identik.
    def makna(self, tipe_step, key, nilai):
        e = self.engine
        if (tipe_step, key) == ("BOX_APPROACH", "target"):
            return e._bap_peran_target({"target": nilai})
        if (tipe_step, key) == ("BOX_APPROACH", "photo"):
            return e._bap_mode_foto({"photo": nilai})
        if (tipe_step, key) == ("BOX_APPROACH", "evade_direction"):
            step = {"evade_direction": nilai}
            return (e._bap_arah_menghindar(step, ROLE_BLUE_BOX),
                    e._bap_arah_menghindar(step, ROLE_GREEN_BOX))
        if (tipe_step, key) == ("BOX_CHANNEL", "mode"):
            return e._boxch_mode_bergerak({"mode": nilai})
        if (tipe_step, key) == ("DOCKING", "prefer"):
            return e._dock_prefer_normal(nilai)
        if (tipe_step, key) == ("PHOTO_BOX", "target"):
            return tuple(e._photo_urutan_target({"target": nilai}))
        if (tipe_step, key) == ("STEER_UNTIL_BOX", "target"):
            return e._steer_box_target_mode({"target": nilai})
        self.fail(f"field select {tipe_step}.{key} belum punya pemeriksaan makna. "
                  f"Tambahkan di sini — dropdown tanpa uji silang boleh saja "
                  f"menawarkan pilihan yang tidak berarti apa-apa di kapal.")

    def test_setiap_field_select_diperiksa(self):
        """Field select baru WAJIB ikut diuji, bukan lolos diam-diam."""
        for tipe, f in self.fields:
            with self.subTest(field=f"{tipe}.{f['key']}"):
                self.makna(tipe, f["key"], f["options"][0]["value"])

    def test_alias_berarti_sama_dengan_nilainya(self):
        """
        Alias ada supaya misi lama yang berisi "kanan" atau "MOVING" tetap
        tersorot benar di dropdown. Kalau sebuah alias ternyata diartikan lain
        oleh kapal, dropdown akan menampilkan satu hal sementara kapal
        mengerjakan hal lain — persis kebingungan yang mau dihilangkan.
        """
        for tipe, f in self.fields:
            for opsi in f["options"]:
                harap = self.makna(tipe, f["key"], opsi["value"])
                for alias in opsi.get("aliases", []):
                    with self.subTest(field=f"{tipe}.{f['key']}", alias=alias):
                        self.assertEqual(self.makna(tipe, f["key"], alias), harap,
                                         f"alias '{alias}' tidak sama dengan "
                                         f"'{opsi['value']}'")

    def test_pilihan_berbeda_berarti_berbeda(self):
        """Dua pilihan yang perilakunya identik cuma menyesatkan operator."""
        for tipe, f in self.fields:
            makna = {}
            for opsi in f["options"]:
                m = self.makna(tipe, f["key"], opsi["value"])
                kunci = repr(m)
                with self.subTest(field=f"{tipe}.{f['key']}", opsi=opsi["value"]):
                    self.assertNotIn(kunci, makna,
                                     f"'{opsi['value']}' berperilaku sama persis "
                                     f"dengan '{makna.get(kunci)}'")
                makna[kunci] = opsi["value"]

    def test_default_ada_di_daftar_pilihan(self):
        """
        nilaiTerpilih() jatuh ke field.default untuk nilai asing. Kalau default-nya
        bukan salah satu option, dropdown-nya tampil KOSONG.
        """
        for tipe, f in self.fields:
            nilai = [o["value"] for o in f["options"]]
            with self.subTest(field=f"{tipe}.{f['key']}"):
                self.assertIn(f["default"], nilai)

    def test_default_panel_sama_dengan_default_kapal(self):
        """
        Nilai kosong harus berarti hal yang sama di dua tempat. Kalau panel
        menampilkan "Mati" sementara kapal menganggap kosong berarti "Berhenti",
        operator membaca setelan yang bukan setelan sesungguhnya.
        """
        for tipe, f in self.fields:
            with self.subTest(field=f"{tipe}.{f['key']}"):
                self.assertEqual(self.makna(tipe, f["key"], f["default"]),
                                 self.makna(tipe, f["key"], ""),
                                 "default panel != perilaku kapal saat field kosong")

    def test_nilai_dan_alias_huruf_kecil_dan_rapi(self):
        """
        nilaiTerpilih() membandingkan nilai yang sudah di-lowercase dengan
        o.value apa adanya. Satu huruf besar di daftar = pilihan itu tidak akan
        pernah tersorot.
        """
        for tipe, f in self.fields:
            for opsi in f["options"]:
                for teks in [opsi["value"], *opsi.get("aliases", [])]:
                    with self.subTest(field=f"{tipe}.{f['key']}", teks=teks):
                        self.assertEqual(teks, teks.strip().lower())

    def test_tidak_ada_alias_yang_ambigu(self):
        """Satu ejaan tidak boleh menunjuk dua pilihan sekaligus."""
        for tipe, f in self.fields:
            terpakai = {}
            for opsi in f["options"]:
                for teks in [opsi["value"], *opsi.get("aliases", [])]:
                    with self.subTest(field=f"{tipe}.{f['key']}", teks=teks):
                        self.assertNotIn(teks, terpakai,
                                         f"'{teks}' dipakai '{opsi['value']}' DAN "
                                         f"'{terpakai.get(teks)}'")
                    terpakai[teks] = opsi["value"]

    def test_setiap_pilihan_punya_label_terbaca(self):
        for tipe, f in self.fields:
            for opsi in f["options"]:
                with self.subTest(field=f"{tipe}.{f['key']}", opsi=opsi["value"]):
                    self.assertTrue(str(opsi.get("label", "")).strip())

    def test_yang_ditampilkan_sama_dengan_yang_dikerjakan_kapal(self):
        """
        Sifat terpenting berkas ini, diuji ujung ke ujung.

        Untuk NILAI APA PUN yang mungkin sudah tersimpan di misi lama — ejaan
        lama, huruf besar, kosong, bahkan salah ketik — pilihan yang disorot
        dropdown harus berarti sama persis dengan yang akan dikerjakan kapal
        untuk nilai aslinya. Kalau tidak, operator membuka misi, melihat
        "Berhenti lalu jepret", dan kapalnya menjepret sambil jalan.

        nilaiTerpilih() yang sesungguhnya dijalankan di node — menuliskan ulang
        logikanya dengan Python cuma akan menguji tiruan yang bisa menyimpang.
        """
        for tipe, f in self.fields:
            ejaan = []
            for o in f["options"]:
                ejaan += [o["value"], o["value"].upper(), f"  {o['value']}  "]
                ejaan += list(o.get("aliases", []))
            ejaan += ["", "   ", "entah-apa", "STOPP", "123"]

            ditampilkan = jalankan_nilai_terpilih(f, ejaan)
            for mentah, tampil in zip(ejaan, ditampilkan):
                with self.subTest(field=f"{tipe}.{f['key']}", nilai=repr(mentah)):
                    self.assertIn(tampil, [o["value"] for o in f["options"]],
                                  "dropdown akan tampil KOSONG untuk nilai ini")
                    self.assertEqual(self.makna(tipe, f["key"], tampil),
                                     self.makna(tipe, f["key"], mentah),
                                     f"panel menampilkan '{tampil}' tapi kapal "
                                     f"memperlakukan '{mentah}' sebagai hal lain")

    def test_tidak_ada_lagi_field_teks_bebas_berisi_pilihan(self):
        """
        Penjaga terhadap kemunduran: field pilihan yang ditulis sebagai teks bebas
        membawa kembali persis risiko salah ketik yang dropdown ini hilangkan.
        Label yang memuat "/" adalah tanda field itu sebetulnya berisi pilihan.
        """
        for step in baca_step_types():
            for f in step.get("fields", []):
                if f.get("type") == "text":
                    with self.subTest(field=f"{step['type']}.{f['key']}"):
                        self.assertNotIn("/", f.get("label", ""),
                                         "sepertinya field pilihan tapi masih teks bebas")


if __name__ == "__main__":
    unittest.main(verbosity=2)
