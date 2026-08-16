<script setup>
import { MapPin, Target, Save, CheckCircle2, AlertTriangle } from 'lucide-vue-next';
import { ref } from 'vue';
import { useWebsocketStore } from '@/stores/websocketStore';
import { useVesselStore } from '@/stores/vesselStore';

const ws = useWebsocketStore();
const vessel = useVesselStore();

const latOffset = ref(0.0);
const lngOffset = ref(0.0);
const applyStatus = ref(null); // null | 'ok' | 'err'

function applyOffsets() {
  if (ws.status !== 'CONNECTED') {
    applyStatus.value = 'err';
    setTimeout(() => { applyStatus.value = null; }, 3000);
    return;
  }
  ws.sendCommand({
    action: 'set_gps_offset',
    lat_offset: parseFloat(latOffset.value),
    lng_offset: parseFloat(lngOffset.value),
  });
  applyStatus.value = 'ok';
  setTimeout(() => { applyStatus.value = null; }, 3000);
}

function autoAlign() {
  if (!vessel.isGpsValid) return;
  // Isi offset dari posisi GPS saat ini untuk referensi
  latOffset.value = parseFloat((vessel.lat || 0).toFixed(7));
  lngOffset.value = parseFloat((vessel.lng || 0).toFixed(7));
}
</script>

<template>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
    <div class="glass-card p-6 space-y-6">
      <div class="flex items-center gap-3">
        <Target class="w-5 h-5 text-primary" />
        <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Manual Offset Correction</span>
      </div>

      <div class="space-y-4">
        <div class="space-y-2">
          <label class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest">Latitude Offset</label>
          <input v-model.number="latOffset" type="number" step="0.000001"
            class="w-full bg-(--bg-secondary) border border-(--border-primary) rounded-lg px-4 py-3 text-sm font-mono text-primary focus:outline-none focus:border-primary" />
        </div>
        <div class="space-y-2">
          <label class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest">Longitude Offset</label>
          <input v-model.number="lngOffset" type="number" step="0.000001"
            class="w-full bg-(--bg-secondary) border border-(--border-primary) rounded-lg px-4 py-3 text-sm font-mono text-primary focus:outline-none focus:border-primary" />
        </div>
      </div>

      <!-- Status Feedback -->
      <transition name="fade">
        <div v-if="applyStatus" :class="['p-3 rounded-xl text-xs font-bold flex items-center gap-2',
          applyStatus === 'ok' ? 'bg-success/10 text-success border border-success/30' : 'bg-danger/10 text-danger border border-danger/30']">
          <CheckCircle2 v-if="applyStatus === 'ok'" class="w-4 h-4" />
          <AlertTriangle v-else class="w-4 h-4" />
          {{ applyStatus === 'ok' ? 'Offset dikirim ke ASV' : 'Gagal: ASV tidak terhubung' }}
        </div>
      </transition>

      <button @click="applyOffsets" :disabled="ws.status !== 'CONNECTED'"
        class="w-full py-3 bg-primary text-slate-900 font-black text-xs uppercase rounded-xl flex items-center justify-center gap-2 hover:brightness-110 transition-all disabled:opacity-40">
        <Save class="w-4 h-4" /> APPLY OFFSETS
      </button>
    </div>

    <div class="glass-card p-6 flex flex-col items-center justify-center text-center space-y-4">
      <div class="w-16 h-16 bg-primary/10 rounded-full flex items-center justify-center">
        <MapPin class="w-8 h-8 text-primary" />
      </div>
      <h4 class="text-sm font-bold text-(--text-primary) uppercase tracking-wider">Auto-Alignment Mode</h4>
      <p class="text-xs text-(--text-secondary) max-w-[200px]">
        Ambil koordinat GPS saat ini sebagai titik referensi offset.
      </p>
      <div v-if="vessel.isGpsValid" class="text-[10px] font-mono text-success">
        GPS: {{ vessel.lat?.toFixed(6) }}, {{ vessel.lng?.toFixed(6) }}
      </div>
      <div v-else class="text-[10px] font-mono text-danger">GPS: NO FIX</div>
      <button @click="autoAlign" :disabled="!vessel.isGpsValid"
        class="bg-card hover:bg-(--bg-secondary) text-(--text-primary) px-6 py-2 rounded-lg text-[10px] font-bold uppercase transition-all disabled:opacity-40">
        Set dari Posisi Saat Ini
      </button>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
