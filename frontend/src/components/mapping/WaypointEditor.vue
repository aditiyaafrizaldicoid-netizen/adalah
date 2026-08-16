<script setup>
import { ref } from 'vue';
import { MousePointer2, PlusCircle, Trash2, Save, Navigation } from 'lucide-vue-next';

defineProps({
  waypoints: { type: Array, default: () => [] }
});

const emit = defineEmits(['add', 'delete', 'clear', 'upload']);

// Mode: 'map' = klik peta untuk add, 'form' = input manual
const addMode = ref('map');
const manualLat = ref('');
const manualLng = ref('');

function submitManual() {
  const lat = parseFloat(manualLat.value);
  const lng = parseFloat(manualLng.value);
  if (isNaN(lat) || isNaN(lng)) return;
  emit('add', lat, lng);
  manualLat.value = '';
  manualLng.value = '';
}
</script>

<template>
  <div class="glass-card p-4 flex flex-col gap-3 border-l-4 border-l-primary">
    <div class="flex items-center justify-between">
      <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">
        Waypoint Editor
        <span class="ml-1 text-primary font-mono">({{ waypoints.length }})</span>
      </span>
      <div class="flex gap-2">
        <button @click="$emit('clear')" :disabled="!waypoints.length"
          title="Hapus semua waypoint"
          class="p-1.5 hover:bg-danger/20 text-danger rounded transition-all disabled:opacity-30">
          <Trash2 class="w-3.5 h-3.5" />
        </button>
        <button @click="$emit('upload')" :disabled="!waypoints.length"
          title="Kirim waypoints ke pipeline misi sebagai GOTO_GPS"
          class="p-1.5 bg-primary/20 text-primary rounded hover:bg-primary hover:text-slate-900 transition-all disabled:opacity-30">
          <Save class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- Waypoint list -->
    <div class="space-y-1.5 max-h-44 overflow-y-auto pr-1">
      <div v-if="!waypoints.length"
        class="text-[10px] text-(--text-muted) italic text-center py-3 border border-dashed border-(--border-subtle) rounded-lg">
        Klik peta untuk tambah waypoint
      </div>
      <div v-for="(wp, i) in waypoints" :key="i"
        class="p-2 bg-card/50 rounded border border-(--border-subtle) flex justify-between items-center group">
        <div>
          <span class="text-[10px] font-bold text-primary block">WP {{ (i+1).toString().padStart(2,'0') }}</span>
          <span class="text-[10px] font-mono text-(--text-secondary)">
            {{ wp.lat.toFixed(6) }}, {{ wp.lng.toFixed(6) }}
          </span>
        </div>
        <button @click="$emit('delete', i)"
          class="opacity-0 group-hover:opacity-100 transition-opacity text-danger hover:bg-danger/10 p-0.5 rounded">
          <Trash2 class="w-3 h-3" />
        </button>
      </div>
    </div>

    <!-- Mode toggle + form -->
    <div class="flex gap-2">
      <button
        @click="addMode = 'map'"
        :class="['flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[10px] font-bold uppercase transition-all',
          addMode === 'map' ? 'bg-primary text-slate-900' : 'bg-card hover:bg-(--bg-secondary) text-(--text-secondary)']">
        <MousePointer2 class="w-3 h-3" /> Klik Peta
      </button>
      <button
        @click="addMode = 'form'"
        :class="['flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[10px] font-bold uppercase transition-all',
          addMode === 'form' ? 'bg-primary text-slate-900' : 'bg-card hover:bg-(--bg-secondary) text-(--text-secondary)']">
        <PlusCircle class="w-3 h-3" /> Input Manual
      </button>
    </div>

    <!-- Manual lat/lng input form -->
    <div v-if="addMode === 'form'" class="flex flex-col gap-2">
      <div class="grid grid-cols-2 gap-2">
        <div>
          <label class="text-[9px] text-(--text-muted) uppercase font-bold block mb-1">Latitude</label>
          <input v-model="manualLat" type="number" step="any" placeholder="-7.9215"
            @keyup.enter="submitManual"
            class="w-full bg-(--bg-secondary) border border-(--border-subtle) rounded px-2 py-1.5 text-[10px] font-mono text-(--text-primary) focus:outline-none focus:border-primary" />
        </div>
        <div>
          <label class="text-[9px] text-(--text-muted) uppercase font-bold block mb-1">Longitude</label>
          <input v-model="manualLng" type="number" step="any" placeholder="112.5973"
            @keyup.enter="submitManual"
            class="w-full bg-(--bg-secondary) border border-(--border-subtle) rounded px-2 py-1.5 text-[10px] font-mono text-(--text-primary) focus:outline-none focus:border-primary" />
        </div>
      </div>
      <button @click="submitManual" :disabled="!manualLat || !manualLng"
        class="flex items-center justify-center gap-2 py-2 bg-primary text-slate-900 rounded-lg text-[10px] font-black uppercase transition-all disabled:opacity-30">
        <Navigation class="w-3 h-3" /> Tambah Waypoint
      </button>
    </div>

    <!-- Send to mission hint -->
    <div v-if="waypoints.length" class="text-[9px] text-(--text-muted) text-center">
      Tekan <span class="text-primary font-bold">💾</span> untuk kirim ke Mission Control sebagai GOTO_GPS
    </div>
  </div>
</template>
