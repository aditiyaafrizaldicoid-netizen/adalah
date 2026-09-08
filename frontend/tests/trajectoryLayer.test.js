/**
 * Uji penggambar lintasan di Mapbox GL (useTrajectoryLayer).
 *
 * Jalankan:  npm test        (dari folder frontend)
 *
 * Saat masih memakai Leaflet, "sambung satu titik ke ujung garis" adalah satu
 * panggilan addLatLng dan Leaflet yang mengurus sisanya. Mapbox GL tidak punya
 * itu: seluruh isi source harus disusun ulang sendiri sebagai GeoJSON. Artinya
 * penyambungan potongan, pengulangan titik jembatan, dan urutan koordinat
 * sekarang jadi kode kita — dan ketiganya gagal DIAM-DIAM.
 *
 * Lintasan yang berlubang di tiap peralihan kendali, atau yang koordinatnya
 * tertukar sehingga tergambar di belahan bumi lain, tetap "berhasil" digambar
 * tanpa satu pun error di konsol. Yang kehilangan bukti geraknya adalah operator,
 * saat lomba, ketika sudah tidak ada waktu memeriksa.
 *
 * Peta-nya ditiru (Mapbox butuh WebGL, tidak ada di Node), tapi store-nya ASLI —
 * yang diuji justru sambungan antara keduanya.
 */
import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";
import { nextTick } from "vue";

const buatSessionStorage = () => {
  const isi = new Map();
  return {
    getItem: (k) => (isi.has(k) ? isi.get(k) : null),
    setItem: (k, v) => isi.set(k, String(v)),
    removeItem: (k) => isi.delete(k),
    clear: () => isi.clear(),
  };
};
globalThis.sessionStorage = buatSessionStorage();

const { useTrajectoryStore } = await import("../src/stores/trajectoryStore.js");
const { useTrajectoryLayer } = await import("../src/composables/useTrajectoryLayer.js");

// ── Peta tiruan ─────────────────────────────────────────────────────────────
/**
 * Menirukan bagian Mapbox GL yang dipakai penggambar, seadanya tapi JUJUR pada
 * dua sifat yang penting: source hanya bisa diganti seluruhnya lewat setData,
 * dan datanya disalin (Mapbox menyerialkannya) sehingga array yang kita ubah
 * belakangan tidak diam-diam ikut mengubah apa yang sudah tergambar.
 */
function petaTiruan() {
  const sources = new Map();
  const layers = new Map();
  const tulis = new Map(); // berapa kali tiap source ditulis ulang
  return {
    addSource(id, opsi) {
      sources.set(id, { data: opsi.data });
      tulis.set(id, 0);
    },
    getSource(id) {
      const s = sources.get(id);
      if (!s) return undefined;
      return {
        setData: (d) => {
          tulis.set(id, tulis.get(id) + 1);
          s.data = JSON.parse(JSON.stringify(d));
        },
      };
    },
    addLayer(spek) {
      layers.set(spek.id, { ...spek, visibility: spek.layout?.visibility ?? "visible" });
    },
    getLayer(id) {
      return layers.get(id);
    },
    removeLayer(id) {
      layers.delete(id);
    },
    removeSource(id) {
      sources.delete(id);
    },
    setLayoutProperty(id, prop, nilai) {
      if (prop === "visibility") layers.get(id).visibility = nilai;
    },
    // Pembantu uji, bukan bagian API Mapbox:
    _tulis: (id) => tulis.get(id) ?? 0,
    _data: (id) => sources.get(id)?.data,
    _fitur: (id) => sources.get(id)?.data?.features ?? [],
    _idSource: () => [...sources.keys()],
    _idLayer: () => [...layers.keys()],
    _layers: () => [...layers.values()],
  };
}

const tel = (lat, lng, tambahan = {}) => ({
  lat, lng, gps_fix: 3, is_connected: true, ...tambahan,
});

const DERAJAT_PER_M = 1 / 111320;
const geserM = (lat, meter) => lat + meter * DERAJAT_PER_M;

const LAT = -7.9215169;
const LNG = 112.5973649;

const SRC_SELESAI = "lintasan-selesai";
const SRC_AKTIF = "lintasan-aktif";

let jam = 1_700_000_000_000;
const aslinyaNow = Date.now;
Date.now = () => jam;
const majuMs = (ms) => { jam += ms; };

let traj, layer, map;

/** Rekam n titik yang bergerak lurus ke utara, 3 m per langkah. */
async function rekamLurus(n, jedaMs = 300) {
  for (let i = 0; i < n; i++) {
    traj.rekam(tel(geserM(LAT, i * 3), LNG));
    majuMs(jedaMs);
  }
  await nextTick();
}

describe("useTrajectoryLayer di atas Mapbox GL", () => {
  beforeEach(() => {
    // WAJIB dikosongkan: store memulihkan lintasan dari sessionStorage saat
    // lahir. Tanpa ini, store "baru" tiap uji justru bangun sudah berisi titik
    // milik uji sebelumnya — dan kegagalannya menyesatkan, karena yang terlihat
    // adalah potongan berlebih yang seolah-olah salah dipotong penggambar.
    sessionStorage.clear();
    setActivePinia(createPinia());
    traj = useTrajectoryStore();
    layer = useTrajectoryLayer();
    map = petaTiruan();
    jam += 1_000_000; // jauhkan dari sisa waktu uji sebelumnya
  });

  describe("pemasangan", () => {
    test("membuat dua source dan empat layer", () => {
      layer.pasang(map);
      assert.deepEqual(map._idSource().sort(), [SRC_AKTIF, SRC_SELESAI].sort());
      // Empat layer, bukan dua: line-dasharray tidak bisa digerakkan properti
      // fitur, jadi garis putus-putus manual butuh layer sendiri.
      assert.equal(map._idLayer().length, 4);
    });

    test("menggambar titik yang sudah terekam SEBELUM peta dibuka", async () => {
      // Inti perekaman di latar belakang: peta baru lahir, lintasannya tidak.
      await rekamLurus(4);
      layer.pasang(map);

      const fitur = map._fitur(SRC_AKTIF);
      assert.equal(fitur.length, 1);
      assert.equal(fitur[0].geometry.coordinates.length, 4);
    });

    test("lepas() membuang semua layer dan source", async () => {
      layer.pasang(map);
      await rekamLurus(3);
      layer.lepas();
      assert.deepEqual(map._idLayer(), []);
      assert.deepEqual(map._idSource(), []);
    });
  });

  describe("urutan koordinat", () => {
    test("GeoJSON [lng, lat], bukan [lat, lng] seperti Leaflet", async () => {
      layer.pasang(map);
      await rekamLurus(2);

      const [lng, lat] = map._fitur(SRC_AKTIF)[0].geometry.coordinates[0];
      assert.ok(Math.abs(lng - LNG) < 1e-6, `bujur ${lng} bukan ${LNG}`);
      assert.ok(Math.abs(lat - LAT) < 1e-6, `lintang ${lat} bukan ${LAT}`);
    });
  });

  describe("penyambungan potongan", () => {
    test("titik menumpuk di satu potongan selama segmen dan kendali tidak berubah", async () => {
      layer.pasang(map);
      await rekamLurus(6);

      assert.equal(map._fitur(SRC_SELESAI).length, 0, "belum ada potongan yang ditutup");
      assert.equal(map._fitur(SRC_AKTIF).length, 1);
      assert.equal(map._fitur(SRC_AKTIF)[0].geometry.coordinates.length, 6);
    });

    test("peralihan manual→otonom memutus potongan TANPA meninggalkan lubang", async () => {
      layer.pasang(map);
      await rekamLurus(4);
      const ujungManual = map._fitur(SRC_AKTIF)[0].geometry.coordinates.slice(-1)[0];

      traj.setStatusMisi("RUNNING");
      traj.rekam(tel(geserM(LAT, 4 * 3), LNG));
      await nextTick();

      const lama = map._fitur(SRC_SELESAI);
      const baru = map._fitur(SRC_AKTIF);
      assert.equal(lama.length, 1, "potongan manual pindah ke source selesai");
      assert.equal(lama[0].properties.oto, false);
      assert.equal(baru[0].properties.oto, true, "potongan baru bertanda otonom");

      // Inilah jembatannya: titik terakhir potongan lama diulang sebagai titik
      // pertama potongan baru. Tanpa ini garis lintasan berlubang tepat di
      // detik kendali berpindah — persis momen yang paling ingin dilihat juri.
      assert.deepEqual(baru[0].geometry.coordinates[0], ujungManual);
    });

    test("telemetri putus memulai segmen baru TANPA jembatan", async () => {
      layer.pasang(map);
      await rekamLurus(4);

      majuMs(30_000); // telemetri putus setengah menit
      traj.rekam(tel(geserM(LAT, 500), LNG));
      await nextTick();

      // Potongan bertitik tunggal sengaja TIDAK dikirim ke peta: LineString satu
      // titik tidak menggambar apa pun, jadi mengirimnya hanya membebani.
      assert.equal(map._fitur(SRC_AKTIF).length, 0, "satu titik belum jadi garis");

      // Waktu HARUS maju: tanpa jeda, 3 m dalam 0 detik terbaca sebagai
      // kecepatan tak hingga dan store menolaknya sebagai glitch GPS.
      majuMs(300);
      traj.rekam(tel(geserM(LAT, 503), LNG));
      await nextTick();

      const baru = map._fitur(SRC_AKTIF)[0];
      // DUA titik, bukan tiga. Kalau titik sebelum putus ikut dijembatani,
      // lintasannya akan digambar sebagai garis lurus menembus daratan sejauh
      // 1,5 km — lintasan yang tidak pernah terjadi, tapi tampak meyakinkan.
      assert.equal(baru.geometry.coordinates.length, 2, "tidak boleh ada titik jembatan");
      assert.ok(
        Math.abs(baru.geometry.coordinates[0][1] - geserM(LAT, 500)) < 1e-6,
        "potongan baru harus mulai dari posisi setelah putus"
      );
    });

    test("potongan ditutup setelah 500 titik", async () => {
      layer.pasang(map);
      await rekamLurus(505);

      assert.equal(map._fitur(SRC_SELESAI).length, 1, "potongan penuh pindah ke selesai");
      assert.equal(map._fitur(SRC_SELESAI)[0].geometry.coordinates.length, 500);

      // 505 titik = 500 di potongan tertutup + 5 sisa, plus 1 titik jembatan.
      assert.equal(map._fitur(SRC_AKTIF)[0].geometry.coordinates.length, 6);
    });
  });

  describe("hemat penulisan source", () => {
    test("source 'selesai' TIDAK ditulis ulang saat kapal berjalan biasa", async () => {
      layer.pasang(map);
      await rekamLurus(20);

      // Inilah inti pemisahan dua source. Potongan aktif memang ditulis ulang
      // terus — isinya dibatasi 500 koordinat, jadi murah. Kalau 'selesai' ikut
      // ditulis, seluruh lintasan (sampai 20.000 titik) diserialkan ulang tiap
      // kapal bergerak setengah meter, dan peta tersendat justru saat berjalan.
      assert.equal(map._tulis(SRC_SELESAI), 1, "hanya penulisan kosong saat dipasang");
      assert.ok(map._tulis(SRC_AKTIF) > 1, "potongan aktif ikut diperbarui");
    });

    test("potongan yang ditutup memicu SATU penulisan 'selesai'", async () => {
      layer.pasang(map);
      const awal = map._tulis(SRC_SELESAI);
      await rekamLurus(505); // melewati batas 500 → satu potongan ditutup
      assert.equal(map._tulis(SRC_SELESAI), awal + 1);
    });
  });

  describe("pembersihan lintasan", () => {
    test("bersihkan() mengosongkan KEDUA source", async () => {
      layer.pasang(map);
      await rekamLurus(505); // sampai ada isi di source 'selesai'
      assert.ok(map._fitur(SRC_SELESAI).length > 0);

      traj.bersihkan();
      await nextTick();

      assert.equal(map._fitur(SRC_SELESAI).length, 0, "potongan lama harus ikut hilang");
      assert.equal(map._fitur(SRC_AKTIF).length, 0);
    });
  });

  describe("sakelar tampilan", () => {
    const semuaTampak = () => map._layers().every((l) => l.visibility === "visible");
    const semuaTersembunyi = () => map._layers().every((l) => l.visibility === "none");

    test("sakelar peta ini saja", () => {
      layer.pasang(map);
      assert.ok(semuaTampak());
      layer.setTampil(false);
      assert.ok(semuaTersembunyi());
      layer.setTampil(true);
      assert.ok(semuaTampak());
    });

    test("sakelar global dan sakelar peta digabung dengan DAN", async () => {
      layer.pasang(map);
      layer.setTampil(false);
      traj.tampilkan = true;
      await nextTick();
      // Menyalakan sakelar global tidak boleh diam-diam menyalakan peta yang
      // sengaja dimatikan operator lewat daftar layer.
      assert.ok(semuaTersembunyi(), "sakelar global tidak boleh menimpa sakelar peta");

      layer.setTampil(true);
      traj.tampilkan = false;
      await nextTick();
      assert.ok(semuaTersembunyi(), "sakelar peta tidak boleh menimpa sakelar global");
    });
  });

  test("Date.now dikembalikan", () => {
    Date.now = aslinyaNow;
    assert.ok(Date.now() > 0);
  });
});
