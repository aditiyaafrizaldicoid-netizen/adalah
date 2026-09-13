/**
 * Uji tampilan COG saat kapal pelan atau diam.
 *
 * Jalankan:  npm test
 *
 * COG (arah GERAK sesungguhnya) hanya bisa dihitung dari vektor kecepatan GPS,
 * dan di bawah 0,3 m/s vektor itu didominasi derau — kapal diam menghasilkan
 * arah yang melompat acak ke segala penjuru. Kapal menandainya cog_valid=false
 * dan MENAHAN nilai sah terakhir (lihat COG_MIN_SPEED_MS di core/state.py).
 *
 * Dulu seluruh tampilan menulis "—" begitu penanda itu jatuh, jadi COG lenyap
 * justru pada dua keadaan paling sering: kapal menunggu di dermaga dan kapal
 * merayap saat manuver. Yang diuji di sini adalah jalan tengahnya — angka sah
 * terakhir tetap terbaca, tapi TIDAK PERNAH menyamar sebagai pengukuran hidup.
 *
 * Dua kegagalan yang dijaga, dan keduanya tidak menimbulkan error:
 *   - memampang 0° sebagai "arah kapal" padahal kapal belum pernah bergerak
 *     sekali pun (nilai lahir `cog` memang 0 — itu utara, bukan "tidak tahu");
 *   - memampang 0° dari kapal yang baru restart seolah-olah arah terakhir yang
 *     teramati.
 */
import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";

const penyimpanan = {
  getItem: () => null, setItem: () => {}, removeItem: () => {}, clear: () => {},
};
globalThis.sessionStorage = penyimpanan;
globalThis.window = { sessionStorage: penyimpanan, addEventListener: () => {} };
globalThis.document = { addEventListener: () => {}, visibilityState: "visible" };

const { useVesselStore } = await import("../src/stores/vesselStore.js");

let jam = 1_700_000_000_000;
const aslinyaNow = Date.now;
Date.now = () => jam;
const majuMs = (ms) => { jam += ms; };

let vessel;
beforeEach(() => {
  setActivePinia(createPinia());
  vessel = useVesselStore();
  jam += 1_000_000;
});

/** Telemetri kapal yang sedang BERGERAK cukup cepat. */
const bergerak = (cog) => ({ cog, cog_valid: true });
/** Telemetri kapal yang pelan/diam — kapal menahan nilai lama di field `cog`. */
const pelan = (cogLama) => ({ cog: cogLama, cog_valid: false });

describe("COG saat kapal pelan atau diam", () => {
  describe("belum pernah bergerak", () => {
    test("tidak ada yang dipampang — 0° bukan 'tidak tahu', itu UTARA", () => {
      vessel.updateTelemetry(pelan(0));
      assert.equal(vessel.cogAda, false);
      assert.equal(vessel.cogTampil, null);
    });

    test("keterangannya menyebut sebabnya", () => {
      vessel.updateTelemetry(pelan(0));
      assert.equal(vessel.cogKeterangan, "kapal belum pernah bergerak");
    });

    test("tidak diperlakukan sebagai nilai tertahan", () => {
      vessel.updateTelemetry(pelan(0));
      assert.equal(vessel.cogTertahanTampil, false, "tidak ada yang ditahan");
    });
  });

  describe("sedang bergerak", () => {
    test("memampang angka hidup, tanpa keterangan", () => {
      vessel.updateTelemetry(bergerak(137.5));
      assert.equal(vessel.cogTampil, 137.5);
      assert.equal(vessel.cogAda, true);
      assert.equal(vessel.cogTertahanTampil, false);
      assert.equal(vessel.cogKeterangan, "");
    });

    test("angka hidup selalu yang terbaru", () => {
      vessel.updateTelemetry(bergerak(10));
      vessel.updateTelemetry(bergerak(200));
      assert.equal(vessel.cogTampil, 200);
    });
  });

  describe("melambat sampai berhenti", () => {
    test("arah sah terakhir TETAP terbaca", () => {
      vessel.updateTelemetry(bergerak(137.5));
      vessel.updateTelemetry(pelan(137.5));
      // Inilah inti permintaannya: kapal berhenti, arah geraknya tidak lenyap
      // dari layar. Arah terakhir kapal bergerak tetap kabar yang berarti.
      assert.equal(vessel.cogTampil, 137.5);
      assert.equal(vessel.cogAda, true);
    });

    test("ditandai tertahan, bukan hidup", () => {
      vessel.updateTelemetry(bergerak(137.5));
      vessel.updateTelemetry(pelan(137.5));
      assert.equal(vessel.cogTertahanTampil, true);
      assert.ok(
        vessel.cogKeterangan.startsWith("tertahan"),
        `keterangan "${vessel.cogKeterangan}" harus menyebut tertahan`
      );
    });

    test("umur ikut bertambah selama telemetri masih masuk", () => {
      vessel.updateTelemetry(bergerak(90));
      majuMs(12_000);
      vessel.updateTelemetry(pelan(90));
      assert.equal(vessel.cogKeterangan, "tertahan — 12 d lalu");

      majuMs(48_000);
      vessel.updateTelemetry(pelan(90));
      assert.equal(vessel.cogKeterangan, "tertahan — 1 mnt lalu");
    });

    test("umur dihitung dari sah TERAKHIR, bukan dari mulai bergerak", () => {
      vessel.updateTelemetry(bergerak(90));
      majuMs(30_000);
      vessel.updateTelemetry(bergerak(95)); // masih bergerak — jam direset
      majuMs(5_000);
      vessel.updateTelemetry(pelan(95));
      assert.equal(vessel.cogKeterangan, "tertahan — 5 d lalu");
    });

    test("umur berjam-jam tetap terbaca", () => {
      vessel.updateTelemetry(bergerak(90));
      majuMs(3600_000 + 300_000); // 1 jam 5 menit
      vessel.updateTelemetry(pelan(90));
      assert.equal(vessel.cogKeterangan, "tertahan — 1 j 5 mnt lalu");
    });
  });

  describe("kapal restart saat base station tetap hidup", () => {
    test("nol dari kapal yang baru boot TIDAK menggantikan arah teramati", () => {
      vessel.updateTelemetry(bergerak(137.5));

      // Kapal restart: `cog` miliknya lahir kembali bernilai 0, dikirim apa
      // adanya dengan cog_valid=false. Kalau base station membaca nilai tertahan
      // dari field kapal alih-alih menyimpan salinannya sendiri, layar akan
      // menyatakan kapal terakhir bergerak ke UTARA — arah yang tidak pernah
      // diukur siapa pun, dipampang dengan penuh percaya diri.
      vessel.updateTelemetry(pelan(0));

      assert.equal(vessel.cogTampil, 137.5, "harus tetap arah teramati terakhir");
    });
  });

  describe("bergerak lagi", () => {
    test("kembali hidup dan keterangannya hilang", () => {
      vessel.updateTelemetry(bergerak(137.5));
      majuMs(20_000);
      vessel.updateTelemetry(pelan(137.5));
      assert.equal(vessel.cogTertahanTampil, true);

      vessel.updateTelemetry(bergerak(210));
      assert.equal(vessel.cogTampil, 210);
      assert.equal(vessel.cogTertahanTampil, false);
      assert.equal(vessel.cogKeterangan, "");
    });
  });

  test("Date.now dikembalikan", () => {
    Date.now = aslinyaNow;
    assert.ok(Date.now() > 0);
  });
});
