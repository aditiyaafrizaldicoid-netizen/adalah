import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { apiUrl } from "@/config/api";
import { authHeaders } from "@/utils/session";
import { useVesselStore } from "./vesselStore";
import { useWebsocketStore } from "./websocketStore";

/**
 * Lintasan arena — "A" atau "B".
 *
 * Menentukan sisi lintasan yang ditandai tiap warna:
 *
 *   Lintasan A : bola hijau KANAN, bola merah KIRI, box biru KIRI,  box hijau KANAN
 *   Lintasan B : bola hijau KIRI,  bola merah KANAN, box biru KANAN, box hijau KIRI
 *
 * B adalah bawaan kapal — konfigurasi yang berlaku sebelum pemilih ini ada.
 *
 * YANG DITAMPILKAN SELALU DARI KAPAL, bukan dari apa yang baru saja diklik
 * operator. Kapal BOLEH menolak perintahnya (mis. selagi misi berjalan), dan
 * tombol yang terlanjur pindah sendiri akan menampilkan setelan yang sebenarnya
 * tidak berlaku — persis jenis rasa aman palsu yang berbahaya di arena.
 *
 * DUA TUJUAN, DUA KEGAGALAN BERBEDA:
 *   - kapal (perintah WebSocket set_track) supaya berlaku SEKARANG;
 *   - backend (PUT /api/v1/pid-config) supaya bertahan setelah kapal di-restart.
 * Database hanya ditulis SETELAH kapal menerima. Menyimpan lebih dulu lalu ditolak
 * kapal membuat DB dan kapal menyimpan dua kebenaran berbeda, dan restart
 * berikutnya diam-diam memakai yang salah.
 */

export const LINTASAN = {
  A: {
    nama: "A",
    sisi: { green: "kanan", red: "kiri", blue_box: "kiri", green_box: "kanan" },
  },
  B: {
    nama: "B",
    sisi: { green: "kiri", red: "kanan", blue_box: "kanan", green_box: "kiri" },
  },
};

/** Batas menunggu balasan kapal sebelum dianggap tidak menjawab. */
const TIMEOUT_ACK_MS = 4000;

export const useTrackStore = defineStore("track", () => {
  const vessel = useVesselStore();

  const mengirim = ref(false);
  const pesan = ref("");
  const pesanGagal = ref(false);
  /** Lintasan yang sedang diminta, selama menunggu jawaban kapal. */
  const menunggu = ref(null);

  let timerAck = null;

  /** Lintasan yang BENAR-BENAR berlaku di kapal. */
  const aktif = computed(() => (vessel.track === "A" ? "A" : "B"));

  const sisiAktif = computed(() => LINTASAN[aktif.value].sisi);

  function bersihkanTimer() {
    if (timerAck) {
      clearTimeout(timerAck);
      timerAck = null;
    }
  }

  /** Simpan ke database supaya bertahan setelah kapal atau backend di-restart. */
  async function simpanKeDb(nama) {
    try {
      const res = await fetch(apiUrl("/api/v1/pid-config"), {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ track: nama }),
      });
      if (!res.ok) {
        return res.status === 401
          ? "sesi kedaluwarsa — login ulang"
          : `HTTP ${res.status}`;
      }
      return "";
    } catch {
      return "backend tidak terhubung";
    }
  }

  /**
   * Balasan kapal. Dipanggil websocketStore saat pesan TRACK_CONFIG datang.
   *
   * Payload SELALU memuat lintasan yang benar-benar aktif di kapal — termasuk saat
   * perintahnya ditolak — jadi tampilan tidak pernah menyimpang dari kenyataan.
   */
  async function terimaAck(payload) {
    bersihkanTimer();
    mengirim.value = false;
    const diminta = menunggu.value;
    menunggu.value = null;

    if (payload?.track) vessel.track = String(payload.track).toUpperCase();

    if (payload?.ok === false) {
      pesanGagal.value = true;
      pesan.value = payload?.reason || "Kapal menolak perubahan lintasan.";
      return;
    }

    // Baru sekarang disimpan: kapal sudah benar-benar memakainya.
    const gagalDb = diminta ? await simpanKeDb(diminta) : "";
    pesanGagal.value = !!gagalDb;
    pesan.value = gagalDb
      ? `Berlaku di kapal, TAPI gagal disimpan (${gagalDb}) — akan kembali ke `
        + `${aktif.value === "A" ? "B" : "A"} setelah kapal di-restart.`
      : `Lintasan ${aktif.value} berlaku di kapal & tersimpan.`;
  }

  /** Pilih lintasan. Aman dipanggil untuk lintasan yang sudah aktif. */
  async function pilih(nama) {
    const target = String(nama || "").toUpperCase();
    if (!LINTASAN[target] || mengirim.value) return false;

    pesan.value = "";
    pesanGagal.value = false;

    const ws = useWebsocketStore();
    if (ws.status !== "CONNECTED") {
      // Kapal tidak terhubung: simpanan DB tetap berguna — kapal membacanya saat
      // boot. Yang TIDAK boleh terjadi adalah tampilan berpura-pura sudah berlaku.
      const gagalDb = await simpanKeDb(target);
      pesanGagal.value = true;
      pesan.value = gagalDb
        ? `Kapal tidak terhubung dan gagal disimpan (${gagalDb}).`
        : `Kapal tidak terhubung. Tersimpan — berlaku saat kapal konek/restart.`;
      return !gagalDb;
    }

    mengirim.value = true;
    menunggu.value = target;
    ws.sendCommand({ action: "set_track", track: target });

    bersihkanTimer();
    timerAck = setTimeout(() => {
      timerAck = null;
      mengirim.value = false;
      menunggu.value = null;
      pesanGagal.value = true;
      pesan.value = "Kapal tidak menjawab. Lintasan yang ditampilkan tetap yang "
        + "berlaku di kapal.";
    }, TIMEOUT_ACK_MS);

    return true;
  }

  return {
    aktif, sisiAktif, mengirim, menunggu, pesan, pesanGagal,
    pilih, terimaAck,
  };
});
