/**
 * Uji penyalinan preset misi.
 *
 * Jalankan:  npm test
 *
 * Preset adalah alur misi yang sudah terbukti jalan di danau. Menyalinnya harus
 * benar-benar aman: yang disalin adalah preset SUMBER, bukan apa pun yang sedang
 * ada di editor, dan editor tidak boleh tersentuh sama sekali.
 *
 * Kegagalan yang dijaga di sini tidak menimbulkan error: menyalin lewat "muat
 * lalu simpan-sebagai" akan MEMBUANG alur misi yang sedang disusun operator dan
 * belum sempat disimpan — kehilangan yang tidak bisa dibatalkan, gara-gara
 * menekan tombol yang niatnya justru mengamankan sesuatu.
 */
import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { createPinia, setActivePinia } from "pinia";

const penyimpanan = {
  getItem: () => null, setItem: () => {}, removeItem: () => {}, clear: () => {},
};
globalThis.sessionStorage = penyimpanan;
globalThis.window = { sessionStorage: penyimpanan, addEventListener: () => {} };
globalThis.document = { addEventListener: () => {}, visibilityState: "visible" };

const { useMissionStore } = await import("../src/stores/missionStore.js");

let mission, dikirim, presetDiServer, balasan;

/** Bentuk baris preset seperti yang dikembalikan backend. */
const baris = (id, name, steps) => ({ id, name, steps: JSON.stringify(steps) });

beforeEach(async () => {
  setActivePinia(createPinia());
  dikirim = [];
  balasan = { ok: true, status: 200 };
  presetDiServer = [
    baris(1, "Lomba Final", [{ type: "BALL_SEEK" }, { type: "BALL_STOP" }]),
    baris(2, "Kosong", []),
  ];

  globalThis.fetch = async (url, opsi = {}) => {
    if ((opsi.method || "GET") === "GET") {
      return {
        ok: true, status: 200,
        json: async () => ({ status: "success", data: presetDiServer }),
      };
    }
    const body = JSON.parse(opsi.body);
    dikirim.push(body);
    if (balasan.ok) {
      presetDiServer.push(baris(presetDiServer.length + 1, body.name,
                                JSON.parse(body.steps)));
    }
    return { ok: balasan.ok, status: balasan.status, json: async () => ({}) };
  };

  mission = useMissionStore();
  await mission.fetchPresets();
});

afterEach(() => {
  mission.resetMission();
  delete globalThis.fetch;
});

const cari = (nama) => mission.presets.find((p) => p.name === nama);

describe("copyPreset", () => {

  test("menyalin langkah dari preset SUMBER, bukan dari editor", async () => {
    mission.steps = [{ type: "DOCKING" }];          // pekerjaan operator di editor
    const hasil = await mission.copyPreset(cari("Lomba Final"));

    assert.equal(hasil.ok, true);
    assert.deepEqual(JSON.parse(dikirim[0].steps),
                     [{ type: "BALL_SEEK" }, { type: "BALL_STOP" }],
                     "yang tersalin justru isi editor");
  });

  test("editor TIDAK tersentuh sama sekali", async () => {
    const kerjaan = [{ type: "DOCKING" }, { type: "FINISH" }];
    mission.steps = kerjaan;
    await mission.copyPreset(cari("Lomba Final"));
    assert.deepEqual(mission.steps, kerjaan,
                     "alur misi yang sedang disusun terbuang saat menyalin");
  });

  test("nama salinan pertama enak dibaca", async () => {
    const hasil = await mission.copyPreset(cari("Lomba Final"));
    assert.equal(hasil.name, "Lomba Final (salinan)");
  });

  test("salinan berikutnya diberi angka, tidak menabrak nama", async () => {
    await mission.copyPreset(cari("Lomba Final"));
    const kedua = await mission.copyPreset(cari("Lomba Final"));
    const ketiga = await mission.copyPreset(cari("Lomba Final"));
    assert.equal(kedua.name, "Lomba Final (salinan 2)");
    assert.equal(ketiga.name, "Lomba Final (salinan 3)");
    const nama = mission.presets.map((p) => p.name);
    assert.equal(new Set(nama).size, nama.length,
                 "ada dua preset bernama sama — tidak bisa dibedakan di daftar");
  });

  test("nama sendiri boleh diberikan", async () => {
    const hasil = await mission.copyPreset(cari("Lomba Final"), "Cadangan Hari-2");
    assert.equal(hasil.name, "Cadangan Hari-2");
    assert.equal(dikirim[0].name, "Cadangan Hari-2");
  });

  test("nama yang sudah dipakai ditolak, tidak menimpa", async () => {
    const hasil = await mission.copyPreset(cari("Lomba Final"), "Kosong");
    assert.equal(hasil.ok, false);
    assert.match(hasil.reason, /sudah dipakai/i);
    assert.equal(dikirim.length, 0, "tidak boleh mengirim apa pun");
  });

  test("preset tanpa langkah tidak bisa disalin", async () => {
    const hasil = await mission.copyPreset(cari("Kosong"));
    assert.equal(hasil.ok, false);
    assert.match(hasil.reason, /tidak punya langkah/i);
    assert.equal(dikirim.length, 0);
  });

  test("salinan muncul di daftar dengan langkah yang sama", async () => {
    await mission.copyPreset(cari("Lomba Final"));
    const salinan = cari("Lomba Final (salinan)");
    assert.ok(salinan, "salinan tidak muncul di daftar");
    assert.deepEqual(salinan.steps, cari("Lomba Final").steps);
  });

  test("mengubah salinan tidak mengubah preset sumber", async () => {
    await mission.copyPreset(cari("Lomba Final"));
    const salinan = cari("Lomba Final (salinan)");
    salinan.steps[0].type = "DIUBAH";
    assert.equal(cari("Lomba Final").steps[0].type, "BALL_SEEK",
                 "salinan dan sumber berbagi objek langkah yang sama");
  });

  test("sesi kedaluwarsa disebut jelas", async () => {
    balasan = { ok: false, status: 401 };
    const hasil = await mission.copyPreset(cari("Lomba Final"));
    assert.equal(hasil.ok, false);
    assert.match(hasil.reason, /login ulang/i);
  });

  test("backend mati tidak melempar", async () => {
    globalThis.fetch = async (url, opsi = {}) => {
      if ((opsi.method || "GET") === "GET") {
        return { ok: true, status: 200, json: async () => ({ status: "success", data: presetDiServer }) };
      }
      throw new Error("ECONNREFUSED");
    };
    const hasil = await mission.copyPreset(cari("Lomba Final"));
    assert.equal(hasil.ok, false);
    assert.match(hasil.reason, /tidak terhubung/i);
  });

  test("preset ngawur tidak bikin crash", async () => {
    for (const buruk of [null, undefined, {}, { steps: "bukan array" }]) {
      const hasil = await mission.copyPreset(buruk);
      assert.equal(hasil.ok, false);
    }
    assert.equal(dikirim.length, 0);
  });
});
