import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { apiUrl } from "@/config/api";
import { authHeaders } from "@/utils/session";
import { useWebsocketStore } from "./websocketStore";
import { useVesselStore } from "./vesselStore";

/**
 * Geofence: batas melingkar yang membatalkan misi kalau kapal keluar darinya.
 *
 * Batasnya digambar di peta lalu dikirim ke DUA tempat, dan keduanya perlu:
 *   - Backend (PUT /api/v1/geofence) supaya bertahan setelah kapal atau backend
 *     di-restart. Kapal membacanya saat boot.
 *   - Kapal (perintah WebSocket set_geofence) supaya berlaku SEKARANG, tanpa
 *     menunggu restart. Ini yang membuat batas bisa diatur di tepi danau.
 *
 * Yang DITAMPILKAN di peta selalu berasal dari telemetri kapal, bukan dari nilai
 * yang baru saja diketik operator — supaya lingkaran di layar mewakili batas yang
 * BENAR-BENAR berlaku di kapal, bukan yang dikira sudah terkirim.
 */
export const useGeofenceStore = defineStore("geofence", () => {
  const vessel = useVesselStore();

  // Nilai yang sedang diedit operator (draft).
  const draft = ref({ enabled: false, lat: 0, lon: 0, radius_m: 60 });
  const isSaving = ref(false);
  const feedback = ref("");

  /** Batas yang BENAR-BENAR berlaku di kapal, dari telemetri. */
  const aktifDiKapal = computed(() => ({
    enabled: vessel.geofenceEnabled === true,
    lat: vessel.geofenceLat || 0,
    lon: vessel.geofenceLon || 0,
    radius_m: vessel.geofenceRadiusM || 0,
  }));

  /** Sudah ada titik pusat yang layak digambar? */
  const punyaPusat = computed(
    () => Math.abs(draft.value.lat) > 1e-7 || Math.abs(draft.value.lon) > 1e-7
  );

  /** Draft berbeda dari yang berlaku di kapal → tombol simpan perlu ditekan. */
  const belumTersimpan = computed(() => {
    const a = aktifDiKapal.value;
    const d = draft.value;
    return (
      a.enabled !== d.enabled ||
      Math.abs(a.radius_m - d.radius_m) > 0.5 ||
      Math.abs(a.lat - d.lat) > 1e-7 ||
      Math.abs(a.lon - d.lon) > 1e-7
    );
  });

  /** Klik di peta menaruh titik pusat. */
  function setCenter(lat, lng) {
    draft.value.lat = lat;
    draft.value.lon = lng;
    feedback.value = "";
  }

  /** Pakai posisi kapal sekarang sebagai pusat — biasanya titik start di dermaga. */
  function pakaiPosisiKapal() {
    if (!vessel.isGpsValid) {
      feedback.value = "GPS kapal belum valid — pusat tidak diubah.";
      return false;
    }
    setCenter(vessel.lat, vessel.lng);
    return true;
  }

  async function muat() {
    try {
      const res = await fetch(apiUrl("/api/v1/geofence"));
      if (!res.ok) return;
      const body = await res.json();
      if (body.status === "success" && body.data) {
        draft.value = {
          enabled: !!body.data.enabled,
          lat: body.data.lat || 0,
          lon: body.data.lon || 0,
          radius_m: body.data.radius_m || 60,
        };
      }
    } catch {
      // Backend tak terjangkau: draft dibiarkan apa adanya. Peta tetap bisa dipakai
      // menggambar, dan simpan akan melaporkan kegagalannya sendiri.
    }
  }

  /**
   * Simpan ke backend DAN kirim ke kapal.
   *
   * Kegagalan salah satunya dilaporkan terpisah: menyimpan ke DB tapi gagal sampai
   * ke kapal adalah keadaan yang sangat berbeda dari sebaliknya, dan operator perlu
   * tahu yang mana — batas yang tersimpan tapi tidak berlaku memberi rasa aman palsu.
   */
  async function simpan() {
    isSaving.value = true;
    feedback.value = "";
    const d = draft.value;
    let okDb = false;
    try {
      const res = await fetch(apiUrl("/api/v1/geofence"), {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          enabled: d.enabled,
          lat: d.lat,
          lon: d.lon,
          radius_m: Number(d.radius_m) || 0,
        }),
      });
      okDb = res.ok;
      if (!okDb) feedback.value = `Gagal menyimpan ke server (HTTP ${res.status}).`;
    } catch {
      feedback.value = "Gagal menyimpan ke server (tidak terhubung).";
    }

    const ws = useWebsocketStore();
    const okKapal = ws.status === "CONNECTED";
    if (okKapal) {
      ws.sendCommand({
        action: "set_geofence",
        enabled: d.enabled,
        lat: d.lat,
        lon: d.lon,
        radius_m: Number(d.radius_m) || 0,
      });
    }

    if (okDb && okKapal) feedback.value = "Tersimpan & dikirim ke kapal.";
    else if (okDb && !okKapal) {
      feedback.value = "Tersimpan di server, TAPI kapal tidak terhubung — "
        + "batas baru berlaku setelah kapal konek/restart.";
    }
    isSaving.value = false;
    return okDb;
  }

  return {
    draft, isSaving, feedback,
    aktifDiKapal, punyaPusat, belumTersimpan,
    setCenter, pakaiPosisiKapal, muat, simpan,
  };
});
