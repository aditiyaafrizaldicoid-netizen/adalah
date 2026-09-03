/**
 * Uji pemilih lintasan (trackStore).
 *
 * Jalankan:  npm test
 *
 * Sifat yang dijaga di sini semuanya soal SATU hal: tampilan tidak boleh pernah
 * menjanjikan setelan yang sebenarnya tidak berlaku di kapal. Lintasan yang
 * keliru membalik arah setiap koreksi kemudi tanpa memunculkan error apa pun,
 * jadi dashboard yang menyorot "A" padahal kapal memakai "B" adalah kegagalan
 * yang paling mahal — operator menurunkan kapal dengan yakin.
 */
import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";

// utils/session.js membaca window.sessionStorage saat modul dimuat, bukan saat
// dipakai — jadi stub-nya harus ada SEBELUM impor di bawah.
const penyimpanan = {
  getItem: () => null, setItem: () => {}, removeItem: () => {}, clear: () => {},
};
globalThis.sessionStorage = penyimpanan;
globalThis.window = { sessionStorage: penyimpanan, addEventListener: () => {} };
globalThis.document = { addEventListener: () => {}, visibilityState: "visible" };

const { useTrackStore } = await import("../src/stores/trackStore.js");
const { useVesselStore } = await import("../src/stores/vesselStore.js");
const { useWebsocketStore } = await import("../src/stores/websocketStore.js");

let track, vessel, ws;
let perintah;      // perintah WS yang terkirim
let tulisanDb;     // body PUT yang sampai ke backend
let balasanDb;     // { ok, status }

beforeEach(() => {
  setActivePinia(createPinia());
  track = useTrackStore();
  vessel = useVesselStore();
  ws = useWebsocketStore();

  perintah = [];
  tulisanDb = [];
  balasanDb = { ok: true, status: 200 };

  ws.status = "CONNECTED";
  ws.sendCommand = (c) => perintah.push(c);
  vessel.track = "B";

  globalThis.fetch = async (url, opsi) => {
    tulisanDb.push(JSON.parse(opsi.body));
    return { ok: balasanDb.ok, status: balasanDb.status };
  };
});

afterEach(() => { delete globalThis.fetch; });

describe("trackStore", () => {

  test("bawaan mengikuti kapal: B", () => {
    assert.equal(track.aktif, "B");
    assert.equal(track.sisiAktif.green, "kiri");
    assert.equal(track.sisiAktif.blue_box, "kanan");
  });

  test("Lintasan A adalah kebalikan penuh dari B", () => {
    vessel.track = "A";
    assert.deepEqual(track.sisiAktif, {
      green: "kanan", red: "kiri", blue_box: "kiri", green_box: "kanan",
    });
  });

  test("mengklik TIDAK langsung memindah tampilan", async () => {
    await track.pilih("A");
    assert.equal(track.aktif, "B",
      "kapal belum menjawab — tampilan tidak boleh mendahului");
    assert.equal(track.menunggu, "A");
    assert.deepEqual(perintah, [{ action: "set_track", track: "A" }]);
  });

  test("database ditulis hanya SETELAH kapal menerima", async () => {
    await track.pilih("A");
    assert.equal(tulisanDb.length, 0, "menulis lebih dulu bisa menyimpan yang ditolak");

    await track.terimaAck({ track: "A", ok: true });
    assert.equal(track.aktif, "A");
    assert.deepEqual(tulisanDb, [{ track: "A" }]);
    assert.equal(track.pesanGagal, false);
  });

  test("kapal menolak: tampilan tetap, database TIDAK ditulis", async () => {
    await track.pilih("A");
    await track.terimaAck({
      track: "B", ok: false, reason: "Misi sedang berjalan.",
    });

    assert.equal(track.aktif, "B", "harus menampilkan yang benar-benar berlaku");
    assert.equal(tulisanDb.length, 0,
      "DB yang menyimpan A sementara kapal memakai B akan salah setelah restart");
    assert.equal(track.pesanGagal, true);
    assert.match(track.pesan, /misi/i);
  });

  test("balasan kapal selalu menang atas yang diklik", async () => {
    await track.pilih("A");
    // Kapal menjawab sesuatu yang lain sama sekali.
    await track.terimaAck({ track: "B", ok: true });
    assert.equal(track.aktif, "B");
  });

  test("kapal offline: disimpan ke DB, dan dikatakan apa adanya", async () => {
    ws.status = "DISCONNECTED";
    const ok = await track.pilih("A");
    assert.equal(ok, true);
    assert.deepEqual(tulisanDb, [{ track: "A" }]);
    assert.equal(perintah.length, 0);
    assert.equal(track.aktif, "B", "belum berlaku — kapal tidak terhubung");
    assert.equal(track.pesanGagal, true);
    assert.match(track.pesan, /tidak terhubung/i);
  });

  test("kapal menerima tapi DB gagal: dikatakan akan kembali setelah restart", async () => {
    balasanDb = { ok: false, status: 500 };
    await track.pilih("A");
    await track.terimaAck({ track: "A", ok: true });
    assert.equal(track.aktif, "A", "di kapal memang sudah berlaku");
    assert.equal(track.pesanGagal, true);
    assert.match(track.pesan, /restart/i);
  });

  test("sesi kedaluwarsa disebut jelas, bukan sekadar HTTP 401", async () => {
    balasanDb = { ok: false, status: 401 };
    await track.pilih("A");
    await track.terimaAck({ track: "A", ok: true });
    assert.match(track.pesan, /login ulang/i);
  });

  test("backend mati tidak melempar", async () => {
    globalThis.fetch = async () => { throw new Error("ECONNREFUSED"); };
    await track.pilih("A");
    await track.terimaAck({ track: "A", ok: true });
    assert.equal(track.pesanGagal, true);
    assert.match(track.pesan, /tidak terhubung/i);
  });

  test("nama lintasan ngawur diabaikan tanpa mengirim apa pun", async () => {
    for (const buruk of ["C", "", null, undefined, "1"]) {
      assert.equal(await track.pilih(buruk), false);
    }
    assert.equal(perintah.length, 0);
    assert.equal(tulisanDb.length, 0);
  });

  test("huruf kecil diterima", async () => {
    await track.pilih("a");
    assert.deepEqual(perintah, [{ action: "set_track", track: "A" }]);
  });

  test("klik beruntun tidak menumpuk perintah", async () => {
    await track.pilih("A");
    await track.pilih("A");
    await track.pilih("B");
    assert.equal(perintah.length, 1, "menunggu jawaban dulu, bukan membanjiri kapal");
  });

  test("telemetri memperbarui tampilan tanpa perlu diklik", () => {
    vessel.updateTelemetry({ track: "a" });
    assert.equal(track.aktif, "A", "dashboard yang baru dibuka harus langsung benar");
  });

  test("telemetri tanpa field track tidak menghapus yang sudah diketahui", () => {
    vessel.track = "A";
    vessel.updateTelemetry({ lat: -7.9, lng: 112.5, gps_fix: 3 });
    assert.equal(track.aktif, "A");
  });
});
