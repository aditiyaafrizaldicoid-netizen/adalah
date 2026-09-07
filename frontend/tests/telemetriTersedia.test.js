/**
 * Uji penanda "field telemetri ini pernah benar-benar dikirim kapal".
 *
 * Jalankan:  npm test
 *
 * Beberapa pembacaan di halaman Monitoring dan Juri — XTE, jarak ke waypoint,
 * RPM, thruster — TIDAK pernah dikirim kapal sama sekali. Nilainya bukan "nol",
 * melainkan tidak ada. Menampilkannya sebagai 0 membuat juri membaca "RPM 0"
 * dan "Thruster 0 %" sebagai kapal yang mati, atau sebagai pengukuran sah yang
 * sebenarnya tidak pernah terjadi.
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

let vessel;
beforeEach(() => {
  setActivePinia(createPinia());
  vessel = useVesselStore();
});

describe("penanda ketersediaan telemetri", () => {

  test("belum ada telemetri: tidak ada yang dianggap tersedia", () => {
    for (const f of ["xte", "dtw", "rpm_l", "thruster_l", "signal_strength"]) {
      assert.equal(vessel.punyaData(f), false, f);
    }
  });

  test("field yang dikirim ditandai tersedia", () => {
    vessel.updateTelemetry({ lat: -7.9, lng: 112.6, signal_strength: 87 });
    assert.equal(vessel.punyaData("signal_strength"), true);
    assert.equal(vessel.signalStrength, 87);
  });

  test("field yang TIDAK dikirim tetap tidak tersedia", () => {
    vessel.updateTelemetry({ lat: -7.9, lng: 112.6, gps_fix: 3 });
    assert.equal(vessel.punyaData("rpm_l"), false,
      "0 pada RPM akan terbaca sebagai kapal mati, bukan sebagai data yang tidak ada");
    assert.equal(vessel.punyaData("xte"), false);
  });

  test("null dan undefined TIDAK dihitung sebagai terkirim", () => {
    vessel.updateTelemetry({ signal_strength: null, xte: undefined, dtw: 0 });
    assert.equal(vessel.punyaData("signal_strength"), false,
      "kapal mengirim null saat RSSI tidak diketahui — itu bukan pengukuran");
    assert.equal(vessel.punyaData("xte"), false);
    assert.equal(vessel.punyaData("dtw"), true, "0 yang SUNGGUH dikirim tetap data");
  });

  test("sekali tersedia tetap tersedia walau pesan berikutnya tidak memuatnya", () => {
    vessel.updateTelemetry({ signal_strength: 90 });
    vessel.updateTelemetry({ lat: -7.9 });
    assert.equal(vessel.punyaData("signal_strength"), true,
      "satu pesan tanpa field itu bukan berarti sensornya hilang");
  });

  test("penanda bersifat reaktif, bukan mutasi diam-diam", () => {
    const sebelum = vessel.punyaData("dtw");
    vessel.updateTelemetry({ dtw: 12.5 });
    assert.equal(sebelum, false);
    assert.equal(vessel.punyaData("dtw"), true);
    assert.equal(vessel.dtw, 12.5);
  });

  test("payload kosong atau rusak tidak melempar", () => {
    for (const buruk of [{}, null, undefined]) {
      vessel.updateTelemetry(buruk);
    }
    assert.equal(vessel.punyaData("xte"), false);
  });
});
