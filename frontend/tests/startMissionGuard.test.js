/**
 * Uji gerbang kendali sebelum misi dijalankan.
 *
 * Jalankan:  npm test
 *
 * BUG LAPANGAN: menekan START saat kendali masih di remote RC dulu tetap
 * mengirim tiga perintah berurutan. Kapal HANYA menolak yang ketiga, karena
 * penjaga di kapal (_blocked_by_remote) cuma melindungi perintah GERAK:
 *
 *   arm             → kapal benar-benar ARMED, baling-baling hidup
 *   set_mode GUIDED → flight controller keluar dari MANUAL; stik remote
 *                     berhenti menggerakkan kapal
 *   start_mission   → ditolak
 *
 * Hasilnya kapal armed, mode salah, tidak menurut remote MAUPUN mini PC, dan
 * dashboard menampilkan misi yang tidak pernah berjalan. Cukup satu kali salah
 * pencet, dan tidak ada satu pun error yang muncul.
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
const { useVesselStore } = await import("../src/stores/vesselStore.js");
const { useWebsocketStore } = await import("../src/stores/websocketStore.js");

let mission, vessel, ws, terkirim;

beforeEach(() => {
  setActivePinia(createPinia());
  mission = useMissionStore();
  vessel = useVesselStore();
  ws = useWebsocketStore();
  terkirim = [];
  ws.status = "CONNECTED";
  ws.sendCommand = (c) => terkirim.push(c.action);
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
  mission.steps = [{ type: "DOCKING" }];
  vessel.manualSource = "minipc";
});

afterEach(() => {
  // startMission memasang setInterval untuk penghitung waktu. Tanpa dihentikan,
  // proses `node --test` tidak pernah keluar dan uji-nya terlihat menggantung.
  mission.resetMission();
  delete globalThis.fetch;
});

describe("gerbang kendali START MISSION", () => {

  test("kendali di remote: TIDAK ada satu perintah pun terkirim", async () => {
    vessel.manualSource = "remote";
    const ok = await mission.startMission();
    assert.equal(ok, false);
    assert.deepEqual(terkirim, [],
      "arm & set_mode lolos penjaga kapal — keduanya tidak boleh dikirim sama sekali");
  });

  test("kendali di remote: kapal TIDAK di-arm", async () => {
    vessel.manualSource = "remote";
    await mission.startMission();
    assert.ok(!terkirim.includes("arm"), "baling-baling tidak boleh hidup");
  });

  test("kendali di remote: mode TIDAK dipindah ke GUIDED", async () => {
    vessel.manualSource = "remote";
    await mission.startMission();
    assert.ok(!terkirim.includes("set_mode"),
      "keluar dari MANUAL membuat stik remote berhenti menggerakkan kapal");
  });

  test("kendali di remote: dashboard TIDAK berkata misi berjalan", async () => {
    vessel.manualSource = "remote";
    const sebelum = mission.missionStatus;
    await mission.startMission();
    assert.equal(mission.missionStatus, sebelum);
    assert.notEqual(mission.missionStatus, "RUNNING");
  });

  test("kendali di remote: operator diberi tahu alasannya", async () => {
    vessel.manualSource = "remote";
    await mission.startMission();
    const w = vessel.warnings.find((x) => x.code === "MISSION_BLOCKED_REMOTE");
    assert.ok(w, "peringatan tidak muncul");
    assert.match(w.message, /remote/i);
  });

  test("kendali di mini PC: urutan perintah utuh seperti semula", async () => {
    const ok = await mission.startMission();
    assert.equal(ok, true);
    assert.deepEqual(terkirim, ["arm", "set_mode", "start_mission"]);
    assert.equal(mission.missionStatus, "RUNNING");
  });

  test("tombol START dimatikan saat kendali di remote, beserta alasannya", () => {
    vessel.manualSource = "remote";
    assert.equal(mission.bisaMulaiMisi, false);
    assert.match(mission.alasanTidakBisaMulai, /remote/i);

    vessel.manualSource = "minipc";
    assert.equal(mission.bisaMulaiMisi, true);
    assert.equal(mission.alasanTidakBisaMulai, "");
  });

  test("pipeline kosong tetap ditolak, dengan alasan yang berbeda", () => {
    mission.steps = [];
    assert.equal(mission.bisaMulaiMisi, false);
    assert.match(mission.alasanTidakBisaMulai, /kosong/i);
  });

  test("kembali ke mini PC langsung membuka tombolnya lagi", async () => {
    vessel.manualSource = "remote";
    await mission.startMission();
    assert.deepEqual(terkirim, []);

    vessel.manualSource = "minipc";
    await mission.startMission();
    assert.deepEqual(terkirim, ["arm", "set_mode", "start_mission"]);
  });
});
