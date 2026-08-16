<script setup>
import { ref, computed } from 'vue';
import {
  Trash2, Save, RefreshCw, CheckCheck,
  FolderOpen, Plus, Flag
} from 'lucide-vue-next';
import { useArenaStore } from '@/stores/arenaStore';

const arena = useArenaStore();

const saveStatus = ref(null); // null | 'ok' | 'err'
const saveMessage = ref('');
const selectedSavedId = ref(null);

// Derived: selected arena from DB
const selectedSaved = computed(() =>
  arena.savedArenas.find((a) => a.id === selectedSavedId.value) || null
);

const TOOLS = [
  { key: 'buoy_red',    label: 'Buoy Merah',   color: 'text-red-500',   bg: 'bg-red-500/20 border-red-500/50',   dot: '🔴' },
  { key: 'buoy_green',  label: 'Buoy Hijau',   color: 'text-green-500', bg: 'bg-green-500/20 border-green-500/50', dot: '🟢' },
  { key: 'trail_green', label: 'Trail Hijau',  color: 'text-green-400', bg: 'bg-green-400/20 border-green-400/50', dot: '🟩' },
  { key: 'trail_blue',  label: 'Trail Biru',   color: 'text-blue-400',  bg: 'bg-blue-400/20 border-blue-400/50',   dot: '🟦' },
];

function toolClass(key) {
  const t = TOOLS.find((x) => x.key === key);
  if (!t) return '';
  return arena.activePlaceTool === key
    ? `${t.bg} border ${t.color} font-black`
    : 'bg-card/50 border border-(--border-subtle) text-(--text-secondary) hover:text-(--text-primary)';
}

async function handleSave() {
  const result = await arena.saveArena();
  saveStatus.value = result.ok ? 'ok' : 'err';
  saveMessage.value = result.message;
  setTimeout(() => { saveStatus.value = null; }, 3000);
}

function handleLoad() {
  if (!selectedSaved.value) return;
  arena.loadArena(selectedSaved.value);
}

async function handleDelete() {
  if (!selectedSavedId.value) return;
  const ok = await arena.deleteArena(selectedSavedId.value);
  if (ok) selectedSavedId.value = null;
}
</script>

<template>
  <div class="glass-card flex flex-col gap-3 border-l-4 border-l-emerald-500 max-h-[calc(100vh-8rem)] overflow-y-auto">

    <!-- Header -->
    <div class="flex items-center justify-between px-4 pt-4">
      <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest flex items-center gap-2">
        <Flag class="w-3.5 h-3.5 text-emerald-400" /> Arena Editor
        <span v-if="arena.totalElements" class="text-emerald-400 font-mono">({{ arena.totalElements }})</span>
      </span>
      <div class="flex gap-1.5">
        <button @click="arena.fetchArenas" title="Refresh DB"
          class="p-1.5 rounded text-(--text-muted) hover:text-primary transition-all">
          <RefreshCw class="w-3 h-3" :class="{ 'animate-spin': arena.isLoadingArenas }" />
        </button>
        <button @click="arena.resetActiveArena" title="Reset arena baru"
          class="p-1.5 rounded text-(--text-muted) hover:text-warning transition-all">
          <Plus class="w-3 h-3" />
        </button>
      </div>
    </div>

    <!-- Arena Metadata -->
    <div class="px-4 space-y-2">
      <input v-model="arena.activeArena.name" placeholder="Nama Arena (wajib)"
        class="w-full bg-(--bg-secondary) border border-(--border-subtle) rounded-lg px-3 py-1.5 text-xs font-mono text-(--text-primary) focus:outline-none focus:border-emerald-400" />
      <input v-model="arena.activeArena.description" placeholder="Deskripsi (opsional)"
        class="w-full bg-(--bg-secondary) border border-(--border-subtle) rounded-lg px-3 py-1.5 text-xs font-mono text-(--text-secondary) focus:outline-none focus:border-emerald-400" />
    </div>

    <div class="border-t border-(--border-subtle)/50" />

    <!-- Tool Palette -->
    <div class="px-4 space-y-2">
      <span class="text-[9px] font-black text-(--text-muted) uppercase tracking-widest">Tempatkan Elemen</span>
      <div class="grid grid-cols-2 gap-1.5">
        <button v-for="t in TOOLS" :key="t.key"
          @click="arena.setTool(t.key)"
          :class="['flex items-center gap-1.5 px-2 py-2 rounded-lg text-[10px] uppercase transition-all', toolClass(t.key)]">
          <span class="text-sm leading-none">{{ t.dot }}</span>
          <span class="font-bold truncate">{{ t.label }}</span>
        </button>
      </div>

      <!-- Active tool hint -->
      <div v-if="arena.activePlaceTool && !arena.isDrawingTrail"
        class="text-[9px] text-primary font-bold text-center py-1 bg-primary/10 rounded-lg">
        Klik peta untuk menempatkan
      </div>

      <!-- Trail drawing controls -->
      <div v-if="arena.isDrawingTrail" class="p-2 bg-blue-500/10 border border-blue-400/30 rounded-lg space-y-2">
        <div class="text-[9px] text-blue-400 font-bold">
          Trail sedang digambar — {{ arena.activeTrailPoints.length }} titik
        </div>
        <div class="text-[9px] text-(--text-muted)">Klik peta untuk tambah titik. Min. 2 titik.</div>
        <button @click="arena.finishTrail" :disabled="arena.activeTrailPoints.length < 2"
          class="w-full py-1.5 bg-blue-500 text-white rounded-lg text-[10px] font-black uppercase disabled:opacity-40 transition-all hover:bg-blue-400">
          <CheckCheck class="w-3 h-3 inline mr-1" /> Selesai Trail
        </button>
      </div>
    </div>

    <div class="border-t border-(--border-subtle)/50" />

    <!-- Buoys List -->
    <div v-if="arena.activeArena.buoys.length" class="px-4 space-y-1.5">
      <span class="text-[9px] font-black text-(--text-muted) uppercase tracking-widest">
        Buoy ({{ arena.activeArena.buoys.length }})
      </span>
      <div v-for="b in arena.activeArena.buoys" :key="b.id"
        class="flex items-center justify-between px-2 py-1.5 bg-card/40 rounded-lg border border-(--border-subtle)/50 group">
        <div class="flex items-center gap-2">
          <span class="text-sm leading-none">{{ b.type === 'red' ? '🔴' : '🟢' }}</span>
          <div>
            <div class="text-[10px] font-bold text-(--text-primary)">{{ b.label }}</div>
            <div class="text-[9px] font-mono text-(--text-muted)">{{ b.lat.toFixed(5) }}, {{ b.lng.toFixed(5) }}</div>
          </div>
        </div>
        <button @click="arena.removeBuoy(b.id)"
          class="opacity-0 group-hover:opacity-100 p-0.5 text-danger hover:bg-danger/10 rounded transition-all">
          <Trash2 class="w-3 h-3" />
        </button>
      </div>
    </div>

    <!-- Trails List -->
    <div v-if="arena.activeArena.trails.length" class="px-4 space-y-1.5">
      <span class="text-[9px] font-black text-(--text-muted) uppercase tracking-widest">
        Trail ({{ arena.activeArena.trails.length }})
      </span>
      <div v-for="t in arena.activeArena.trails" :key="t.id"
        class="flex items-center justify-between px-2 py-1.5 bg-card/40 rounded-lg border border-(--border-subtle)/50 group">
        <div class="flex items-center gap-2">
          <span class="text-sm leading-none">{{ t.type === 'green' ? '🟩' : '🟦' }}</span>
          <div>
            <div class="text-[10px] font-bold text-(--text-primary)">{{ t.label }}</div>
            <div class="text-[9px] font-mono text-(--text-muted)">{{ t.points.length }} titik</div>
          </div>
        </div>
        <button @click="arena.removeTrail(t.id)"
          class="opacity-0 group-hover:opacity-100 p-0.5 text-danger hover:bg-danger/10 rounded transition-all">
          <Trash2 class="w-3 h-3" />
        </button>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!arena.totalElements && !arena.isDrawingTrail"
      class="mx-4 py-4 border border-dashed border-(--border-subtle) rounded-lg text-center text-[10px] text-(--text-muted) italic">
      Pilih tool lalu klik peta untuk tambah elemen
    </div>

    <div class="border-t border-(--border-subtle)/50" />

    <!-- Action Buttons -->
    <div class="px-4 space-y-2">
      <button @click="handleSave" :disabled="!arena.activeArena.name.trim()"
        :class="['w-full py-2 rounded-xl text-[10px] font-black uppercase transition-all flex items-center justify-center gap-2',
          saveStatus === 'ok' ? 'bg-success text-slate-900' :
          saveStatus === 'err' ? 'bg-danger text-white' :
          'bg-emerald-500 text-slate-900 hover:brightness-110 disabled:opacity-40']">
        <Save class="w-3.5 h-3.5" />
        {{ saveStatus === 'ok' ? saveMessage : saveStatus === 'err' ? saveMessage : 'Simpan Arena ke DB' }}
      </button>

      <button v-if="arena.totalElements" @click="arena.clearAll"
        class="w-full py-1.5 bg-card border border-(--border-subtle) text-(--text-secondary) rounded-lg text-[10px] font-bold uppercase transition-all hover:bg-danger/10 hover:text-danger hover:border-danger/30 flex items-center justify-center gap-1.5">
        <Trash2 class="w-3 h-3" /> Bersihkan Semua Elemen
      </button>
    </div>

    <div class="border-t border-(--border-subtle)/50" />

    <!-- Load from DB -->
    <div class="px-4 pb-4 space-y-2">
      <span class="text-[9px] font-black text-(--text-muted) uppercase tracking-widest flex items-center gap-1.5">
        <FolderOpen class="w-3 h-3" /> Arena Tersimpan ({{ arena.savedArenas.length }})
      </span>

      <div v-if="!arena.savedArenas.length"
        class="text-[10px] text-(--text-muted) italic text-center py-2">
        Belum ada arena tersimpan di DB
      </div>
      <template v-else>
        <select v-model="selectedSavedId"
          class="w-full bg-(--bg-secondary) border border-(--border-subtle) rounded-lg px-3 py-1.5 text-[10px] text-(--text-primary) focus:outline-none focus:border-emerald-400">
          <option :value="null" disabled>— Pilih arena —</option>
          <option v-for="a in arena.savedArenas" :key="a.id" :value="a.id">
            {{ a.name }} ({{ (a.buoys || []).length }}🔴🟢 / {{ (a.trails || []).length }} trail)
          </option>
        </select>
        <div class="flex gap-2">
          <button @click="handleLoad" :disabled="!selectedSavedId"
            class="flex-1 py-1.5 bg-primary/20 text-primary rounded-lg text-[10px] font-black uppercase transition-all hover:bg-primary hover:text-slate-900 disabled:opacity-30">
            Load
          </button>
          <button @click="handleDelete" :disabled="!selectedSavedId"
            class="py-1.5 px-3 bg-danger/10 text-danger rounded-lg text-[10px] font-bold uppercase transition-all hover:bg-danger hover:text-white disabled:opacity-30">
            <Trash2 class="w-3 h-3" />
          </button>
        </div>
      </template>
    </div>
  </div>
</template>
