<script setup>
/**
 * Panel geofence — batas melingkar yang membatalkan misi kalau kapal keluar.
 *
 * Sebelum panel ini, batasnya hanya bisa diatur dengan menyunting .env di Mini PC
 * lewat SSH lalu me-restart kapal. Di tepi danau itu berarti membuka laptop kedua,
 * dan dalam praktiknya berarti geofence-nya tidak pernah dipasang sama sekali.
 */
import { onMounted } from "vue";
import { Shield, ShieldOff, Crosshair, Save, MapPin, AlertTriangle } from "lucide-vue-next";
import { useGeofenceStore } from "@/stores/geofenceStore";
import { useVesselStore } from "@/stores/vesselStore";

const geofence = useGeofenceStore();
const vessel = useVesselStore();

onMounted(geofence.muat);
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h3 class="text-sm font-black text-(--text-primary) uppercase tracking-widest flex items-center gap-2">
        <component :is="geofence.draft.enabled ? Shield : ShieldOff"
          class="w-4 h-4" :class="geofence.draft.enabled ? 'text-warning' : 'text-(--text-muted)'" />
        Geofence
      </h3>
      <span class="text-[9px] font-bold px-2 py-0.5 rounded"
        :class="geofence.aktifDiKapal.enabled
          ? 'bg-warning/10 text-warning' : 'bg-card text-(--text-muted)'">
        {{ geofence.aktifDiKapal.enabled
          ? `AKTIF ${geofence.aktifDiKapal.radius_m.toFixed(0)} m` : 'TIDAK AKTIF' }}
      </span>
    </div>

    <p class="text-[10px] leading-relaxed text-(--text-secondary)">
      Klik di peta untuk menaruh titik pusat, lalu atur jari-jarinya. Kalau kapal
      keluar batas lebih dari 2 detik, misi dibatalkan otomatis — kapal
      <b>tidak</b> di-disarm, jadi masih bisa dikemudikan pulang lewat remote.
    </p>

    <!-- Aktif / nonaktif -->
    <button type="button" @click="geofence.draft.enabled = !geofence.draft.enabled"
      class="w-full flex items-center justify-between p-3 rounded-lg border transition-colors"
      :class="geofence.draft.enabled
        ? 'bg-warning/10 border-warning/40 text-warning'
        : 'bg-card border-(--border-subtle) text-(--text-secondary)'">
      <span class="text-xs font-bold uppercase tracking-wider">
        {{ geofence.draft.enabled ? 'Geofence dinyalakan' : 'Geofence dimatikan' }}
      </span>
      <span class="text-[9px] font-mono opacity-70">
        {{ geofence.draft.enabled ? 'klik untuk matikan' : 'klik untuk nyalakan' }}
      </span>
    </button>

    <!-- Titik pusat -->
    <div class="space-y-2">
      <label class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-wider">
        Titik Pusat
      </label>
      <div class="flex items-center gap-2 p-2.5 rounded-lg bg-(--bg-secondary) border border-(--border-subtle)">
        <MapPin class="w-3.5 h-3.5 text-(--text-muted) shrink-0" />
        <span class="text-[11px] font-mono text-(--text-primary) truncate">
          {{ geofence.punyaPusat
            ? `${geofence.draft.lat.toFixed(6)}, ${geofence.draft.lon.toFixed(6)}`
            : 'Belum ditentukan — klik di peta' }}
        </span>
      </div>
      <button type="button" @click="geofence.pakaiPosisiKapal()"
        class="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider bg-card border border-(--border-subtle) text-(--text-secondary) hover:text-primary transition-colors">
        <Crosshair class="w-3.5 h-3.5" /> Pakai posisi kapal sekarang
      </button>
    </div>

    <!-- Jari-jari -->
    <div class="space-y-2">
      <label class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-wider flex justify-between">
        <span>Jari-jari</span>
        <span class="font-mono text-primary">{{ Number(geofence.draft.radius_m).toFixed(0) }} m</span>
      </label>
      <input type="range" min="10" max="300" step="5" v-model.number="geofence.draft.radius_m"
        class="w-full accent-primary" />
      <input type="number" min="0" step="5" v-model.number="geofence.draft.radius_m"
        class="w-full bg-(--bg-secondary) border border-(--border-subtle) rounded-lg px-3 py-2 text-sm font-mono text-(--text-primary) focus:outline-none focus:border-primary" />
    </div>

    <!-- Simpan -->
    <button type="button" @click="geofence.simpan()"
      :disabled="geofence.isSaving || (geofence.draft.enabled && !geofence.punyaPusat)"
      class="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-xs font-black uppercase tracking-widest bg-primary text-slate-900 disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition-all">
      <Save class="w-4 h-4" />
      {{ geofence.isSaving ? 'Menyimpan...' : 'Simpan & kirim ke kapal' }}
    </button>

    <div v-if="geofence.draft.enabled && !geofence.punyaPusat"
      class="flex items-start gap-2 text-[10px] text-warning">
      <AlertTriangle class="w-3.5 h-3.5 shrink-0 mt-px" />
      <span>Tentukan titik pusat dulu — klik di peta atau pakai posisi kapal.</span>
    </div>

    <div v-if="geofence.belumTersimpan && geofence.punyaPusat"
      class="text-[10px] text-(--text-secondary) flex items-start gap-2">
      <span class="w-3 h-3 rounded-full border-2 border-dashed border-sky-400 shrink-0 mt-0.5"></span>
      <span>Lingkaran garis putus di peta = batas yang belum disimpan.</span>
    </div>

    <div v-if="geofence.feedback" class="text-[10px] font-bold text-(--text-secondary)">
      {{ geofence.feedback }}
    </div>

    <p v-if="!vessel.isConnected" class="text-[10px] text-(--text-muted)">
      Kapal tidak terhubung — batas tetap bisa disimpan, dan akan berlaku begitu
      kapal konek.
    </p>
  </div>
</template>
