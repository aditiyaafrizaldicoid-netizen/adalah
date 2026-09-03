/**
 * Uji perekam lintasan (trajectoryStore).
 *
 * Jalankan:  npm run test        (dari folder frontend)
 *
 * Yang diuji di sini bukan "apakah titik bertambah", melainkan hal-hal yang
 * salahnya TIDAK menimbulkan error dan baru ketahuan setelah lomba selesai:
 * lintasan yang menyambung lurus menembus daratan setelah telemetri putus,
 * jejak yang tampak meyakinkan padahal GPS belum terkunci, dan buffer yang
 * membengkak sampai tab browser tersendat di tengah misi.
 *
 * Store-nya dijalankan APA ADANYA lewat Pinia — bukan tiruan logikanya, karena
 * tiruan justru bisa menyimpang diam-diam dari yang berjalan di dashboard.
 */
import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";

// sessionStorage tidak ada di Node. Distub supaya jalur simpan/pulihkan benar-benar
// ikut teruji, bukan cuma dilewati diam-diam oleh try/catch di dalam store.
const buatSessionStorage = () => {
  const isi = new Map();
  return {
    getItem: (k) => (isi.has(k) ? isi.get(k) : null),
    setItem: (k, v) => isi.set(k, String(v)),
    removeItem: (k) => isi.delete(k),
    clear: () => isi.clear(),
    _isi: isi,
  };
};
globalThis.sessionStorage = buatSessionStorage();

const { useTrajectoryStore } = await import("../src/stores/trajectoryStore.js");

/** Payload telemetri yang sah, seperti yang dikirim kapal. */
const tel = (lat, lng, tambahan = {}) => ({
  lat, lng, gps_fix: 3, is_connected: true, ...tambahan,
});

/** ~1,11 m per 0,00001 derajat lintang di khatulistiwa. */
const DERAJAT_PER_M = 1 / 111320;
const geserM = (lat, meter) => lat + meter * DERAJAT_PER_M;

const LAT = -7.9215169;
const LNG = 112.5973649;

let traj;
let jam;

/** Kendalikan waktu supaya uji tidak bergantung pada jeda nyata. */
function pasangJam() {
  jam = 1_700_000_000_000;
  Date.now = () => jam;
}
const majuMs = (ms) => { jam += ms; };

describe("trajectoryStore", () => {
  beforeEach(() => {
    globalThis.sessionStorage = buatSessionStorage();
    pasangJam();
    setActivePinia(createPinia());
    traj = useTrajectoryStore();
  });

  // ── Gerbang mutu data ─────────────────────────────────────────────────────

  describe("gerbang mutu data", () => {
    test("titik sah direkam", () => {
      traj.rekam(tel(LAT, LNG));
      assert.equal(traj.jumlahTitik, 1);
    });

    test("GPS belum terkunci tidak pernah direkam", () => {
      for (const fix of [0, 1]) {
        traj.rekam(tel(LAT, LNG, { gps_fix: fix }));
      }
      assert.equal(traj.jumlahTitik, 0, "fix 0/1 bukan posisi, cuma tebakan penerima");
      assert.equal(traj.tolakFix, 2);
    });

    test("koordinat null saat kapal belum punya fix tidak bikin NaN", () => {
      traj.rekam(tel(null, null, { gps_fix: 0 }));
      traj.rekam(tel(undefined, undefined, { gps_fix: 3 }));
      assert.equal(traj.jumlahTitik, 0);
      assert.equal(traj.jarakTotalM, 0, "jarak tidak boleh jadi NaN");
    });

    test("Null Island (0,0) ditolak", () => {
      traj.rekam(tel(0, 0));
      assert.equal(traj.jumlahTitik, 0);
    });

    test("koordinat di luar rentang bumi ditolak", () => {
      traj.rekam(tel(91, LNG));
      traj.rekam(tel(LAT, 181));
      assert.equal(traj.jumlahTitik, 0);
    });

    test("flight controller putus: koordinat beku tidak direkam", () => {
      traj.rekam(tel(LAT, LNG));
      majuMs(200);
      traj.rekam(tel(geserM(LAT, 5), LNG, { is_connected: false }));
      assert.equal(traj.jumlahTitik, 1, "posisi terakhir yang membeku bukan posisi sekarang");
      assert.equal(traj.tolakFcPutus, 1);
    });
  });

  // ── Penjarangan ───────────────────────────────────────────────────────────

  describe("penjarangan", () => {
    test("kapal diam tidak menumpuk titik", () => {
      traj.rekam(tel(LAT, LNG));
      for (let i = 0; i < 100; i++) {
        majuMs(100);
        // Derau GPS beberapa sentimeter, seperti kapal terikat di dermaga.
        traj.rekam(tel(geserM(LAT, 0.05 * Math.sin(i)), LNG));
      }
      assert.equal(traj.jumlahTitik, 1, "derau di tempat tidak boleh jadi lintasan");
    });

    test("gerakan di atas ambang direkam", () => {
      traj.rekam(tel(LAT, LNG));
      majuMs(500);
      traj.rekam(tel(geserM(LAT, 2), LNG));
      assert.equal(traj.jumlahTitik, 2);
      assert.ok(Math.abs(traj.jarakTotalM - 2) < 0.1, `jarak ${traj.jarakTotalM} ≠ ~2 m`);
    });

    test("lompatan yang mustahil secara fisik ditolak", () => {
      traj.rekam(tel(LAT, LNG));
      majuMs(100);
      // 500 m dalam 0,1 detik = 18.000 km/jam. Itu glitch, bukan gerakan.
      traj.rekam(tel(geserM(LAT, 500), LNG));
      assert.equal(traj.jumlahTitik, 1);
      assert.equal(traj.tolakLompatan, 1);
      assert.equal(traj.jarakTotalM, 0, "glitch tidak boleh menambah jarak tempuh");
    });
  });

  // ── Segmentasi: inti pencegah lintasan palsu ─────────────────────────────

  describe("segmentasi", () => {
    test("jeda telemetri memulai segmen baru, bukan garis lurus menembus daratan", () => {
      traj.rekam(tel(LAT, LNG));
      majuMs(30_000); // telemetri putus setengah menit
      traj.rekam(tel(geserM(LAT, 300), LNG));

      assert.equal(traj.jumlahTitik, 2);
      assert.equal(traj.jumlahSegmen, 2, "dua titik itu tidak boleh disambung");
      const seg = traj.ambilSegmen();
      assert.equal(seg.length, 2);
      assert.equal(seg[0].titik.length, 1);
      assert.equal(seg[1].titik.length, 1);
    });

    test("jarak tempuh tidak melonjak karena jeda", () => {
      traj.rekam(tel(LAT, LNG));
      majuMs(30_000);
      traj.rekam(tel(geserM(LAT, 300), LNG));
      assert.equal(traj.jarakTotalM, 0, "jarak melintasi jeda tidak pernah ditempuh");
    });

    test("fix hilang lalu kembali memulai segmen baru", () => {
      traj.rekam(tel(LAT, LNG));
      majuMs(100);
      traj.rekam(tel(LAT, LNG, { gps_fix: 0 }));
      majuMs(100);
      traj.rekam(tel(geserM(LAT, 3), LNG));
      assert.equal(traj.jumlahSegmen, 2);
    });

    test("gerakan mulus tetap satu segmen", () => {
      for (let i = 0; i < 20; i++) {
        traj.rekam(tel(geserM(LAT, i * 2), LNG));
        majuMs(500);
      }
      assert.equal(traj.jumlahSegmen, 1);
      assert.equal(traj.ambilSegmen().length, 1);
    });
  });

  // ── Penandaan otonom vs manual ───────────────────────────────────────────

  describe("otonom vs manual", () => {
    test("titik ditandai otonom saat misi berjalan", () => {
      traj.setStatusMisi("RUNNING");
      traj.rekam(tel(LAT, LNG));
      assert.equal(traj.ambilTitik()[0].oto, true);
    });

    test("perekaman TIDAK berhenti saat misi selesai", () => {
      traj.setStatusMisi("RUNNING");
      traj.rekam(tel(LAT, LNG));
      traj.setStatusMisi("FINISHED");
      majuMs(500);
      traj.rekam(tel(geserM(LAT, 3), LNG));
      assert.equal(traj.jumlahTitik, 2, "kendali manual harus tetap terekam");
      assert.equal(traj.ambilTitik()[1].oto, false);
    });

    test("status misi yang berhenti mengalir dianggap basi", () => {
      traj.setStatusMisi("RUNNING");
      traj.rekam(tel(LAT, LNG));
      // Kapal berhenti mengirim MISSION_STATUS tanpa status penutup.
      majuMs(5000);
      traj.rekam(tel(geserM(LAT, 3), LNG));
      assert.equal(traj.ambilTitik()[1].oto, false,
        "tanpa kedaluwarsa, sisa lintasan salah warna selamanya");
    });

    test("peralihan mode dipotong jadi bagian terpisah, tapi tersambung", () => {
      traj.setStatusMisi("RUNNING");
      traj.rekam(tel(LAT, LNG));
      majuMs(300);
      traj.rekam(tel(geserM(LAT, 3), LNG));
      traj.setStatusMisi("FINISHED");
      majuMs(300);
      traj.rekam(tel(geserM(LAT, 6), LNG));

      const seg = traj.ambilSegmen();
      assert.equal(seg.length, 2, "otonom dan manual digambar terpisah");
      assert.equal(seg[0].oto, true);
      assert.equal(seg[1].oto, false);
      // Titik terakhir bagian pertama diulang di awal bagian kedua — tanpa itu
      // garisnya berlubang tepat di titik peralihan kendali.
      assert.deepEqual(
        [seg[1].titik[0].lat, seg[1].titik[0].lng],
        [seg[0].titik.at(-1).lat, seg[0].titik.at(-1).lng]
      );
    });
  });

  // ── Batas memori ─────────────────────────────────────────────────────────

  describe("batas memori", () => {
    test("buffer tidak tumbuh tanpa batas, dan indeks lama ditandai kedaluwarsa", () => {
      const epochAwal = traj.epoch;
      for (let i = 0; i < 21_000; i++) {
        traj.rekam(tel(geserM(LAT, i * 1), LNG));
        majuMs(200);
      }
      assert.ok(traj.jumlahTitik <= 20_000, `buffer membengkak: ${traj.jumlahTitik}`);
      assert.ok(traj.titikDibuang > 0);
      assert.ok(traj.epoch > epochAwal,
        "penggambar harus diberi tahu bahwa indeks lamanya sudah tidak valid");
    });

    test("jarak tempuh tetap utuh walau titik lama dibuang", () => {
      for (let i = 0; i < 21_000; i++) {
        traj.rekam(tel(geserM(LAT, i * 1), LNG));
        majuMs(200);
      }
      // 21.000 langkah @ 1 m; toleransi longgar untuk pembulatan proyeksi.
      assert.ok(traj.jarakTotalM > 20_000,
        `jarak ${traj.jarakTotalM} m — riwayat yang dibuang ikut hilang`);
    });
  });

  // ── Kendali operator ─────────────────────────────────────────────────────

  describe("kendali operator", () => {
    test("jeda menghentikan perekaman, lanjut mengembalikannya", () => {
      traj.merekam = false;
      traj.rekam(tel(LAT, LNG));
      assert.equal(traj.jumlahTitik, 0);
      traj.merekam = true;
      traj.rekam(tel(LAT, LNG));
      assert.equal(traj.jumlahTitik, 1);
    });

    test("hapus mengosongkan semuanya termasuk statistik", () => {
      for (let i = 0; i < 5; i++) {
        traj.rekam(tel(geserM(LAT, i * 3), LNG));
        majuMs(300);
      }
      traj.bersihkan();
      assert.equal(traj.jumlahTitik, 0);
      assert.equal(traj.jarakTotalM, 0);
      assert.equal(traj.jumlahSegmen, 0);
      assert.equal(traj.durasiMs, 0);
      assert.equal(sessionStorage.getItem("asv.trajectory.v1"), null);
    });
  });

  // ── Ketahanan terhadap refresh ───────────────────────────────────────────

  describe("bertahan saat halaman di-refresh", () => {
    test("lintasan dipulihkan dari sesi", () => {
      for (let i = 0; i < 30; i++) {
        traj.rekam(tel(geserM(LAT, i * 3), LNG));
        majuMs(1000);
      }
      // Refresh nyata memicu pagehide/visibilitychange; di Node keduanya tidak
      // ada, jadi jalur yang sama dipanggil langsung.
      traj.simpanSekarang();
      const sebelum = traj.jumlahTitik;
      const jarakSebelum = traj.jarakTotalM;
      assert.ok(sessionStorage.getItem("asv.trajectory.v1"), "belum sempat tersimpan");

      // Refresh: Pinia baru, sessionStorage yang sama.
      setActivePinia(createPinia());
      const lagi = useTrajectoryStore();
      assert.equal(lagi.jumlahTitik, sebelum);
      assert.ok(Math.abs(lagi.jarakTotalM - jarakSebelum) < 0.001);
    });

    test("titik pertama setelah dipulihkan TIDAK disambung ke titik lama", () => {
      for (let i = 0; i < 30; i++) {
        traj.rekam(tel(geserM(LAT, i * 3), LNG));
        majuMs(1000);
      }
      traj.simpanSekarang();
      setActivePinia(createPinia());
      const lagi = useTrajectoryStore();
      const segSebelum = lagi.jumlahSegmen;
      lagi.rekam(tel(geserM(LAT, 500), LNG));
      assert.equal(lagi.jumlahSegmen, segSebelum + 1,
        "jeda antara simpanan terakhir dan sekarang panjangnya tidak diketahui");
    });

    test("data sesi yang rusak tidak membuat aplikasi gagal start", () => {
      sessionStorage.setItem("asv.trajectory.v1", "{bukan json}");
      setActivePinia(createPinia());
      const lagi = useTrajectoryStore();
      assert.equal(lagi.jumlahTitik, 0);
      lagi.rekam(tel(LAT, LNG));
      assert.equal(lagi.jumlahTitik, 1, "harus tetap bisa merekam");
    });

    test("titik rusak di dalam simpanan disaring", () => {
      sessionStorage.setItem("asv.trajectory.v1", JSON.stringify({
        v: 1, jarakTotalM: 10, titikDibuang: 0,
        titik: [[LAT, LNG, 1, 0, 0], [null, null, 2, 0, 0], [999, 999, 3, 0, 0]],
      }));
      setActivePinia(createPinia());
      const lagi = useTrajectoryStore();
      assert.equal(lagi.jumlahTitik, 1);
    });

    test("sessionStorage yang menolak menulis tidak menghentikan perekaman", () => {
      globalThis.sessionStorage = {
        getItem: () => null,
        setItem: () => { throw new Error("QuotaExceededError"); },
        removeItem: () => {},
      };
      setActivePinia(createPinia());
      const lagi = useTrajectoryStore();
      for (let i = 0; i < 30; i++) {
        lagi.rekam(tel(geserM(LAT, i * 3), LNG));
        majuMs(1000);
      }
      assert.equal(lagi.jumlahTitik, 30,
        "gagal menyimpan cadangan jauh lebih ringan daripada berhenti merekam");
    });
  });

  // ── Kontrak untuk penggambar ─────────────────────────────────────────────

  describe("kontrak penggambar", () => {
    test("versi bertambah hanya saat ada titik baru", () => {
      const v0 = traj.versi;
      traj.rekam(tel(LAT, LNG, { gps_fix: 0 }));
      assert.equal(traj.versi, v0, "penolakan tidak boleh memicu gambar ulang");
      traj.rekam(tel(LAT, LNG));
      assert.equal(traj.versi, v0 + 1);
    });

    test("ambilSejak mengembalikan hanya yang belum digambar", () => {
      for (let i = 0; i < 5; i++) {
        traj.rekam(tel(geserM(LAT, i * 3), LNG));
        majuMs(300);
      }
      assert.equal(traj.ambilSejak(3).length, 2);
      assert.equal(traj.ambilSejak(5).length, 0);
      assert.equal(traj.ambilSejak(99).length, 0, "indeks lewat batas jangan melempar");
    });

    test("array titik bukan proxy reaktif", () => {
      traj.rekam(tel(LAT, LNG));
      const arr = traj.ambilTitik();
      assert.ok(Array.isArray(arr));
      assert.equal(arr[0].lat, LAT, "titik harus objek biasa, bukan proxy dalam");
    });
  });
});
