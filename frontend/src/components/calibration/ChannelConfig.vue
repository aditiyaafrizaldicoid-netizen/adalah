<script setup>
import { ref, computed, watch } from 'vue';
import { Settings, Zap, Navigation2, RefreshCw, Save, CheckCircle, AlertTriangle, Info } from 'lucide-vue-next';
import { useChannelConfigStore } from '@/stores/channelConfigStore';
import { useWebsocketStore } from '@/stores/websocketStore';

const cfg = useChannelConfigStore();
const ws = useWebsocketStore();

// Local draft state — hanya dikirim saat klik "Apply"
const draft = ref({
  thrusterLeftCh: cfg.thrusterLeftCh,
  thrusterRightCh: cfg.thrusterRightCh,
  servoLeftCh: cfg.servoLeftCh,
  servoRightCh: cfg.servoRightCh,
  servoMethod: cfg.servoMethod,
});

// Sync draft jika store berubah dari ASV (CHANNEL_CONFIG event)
watch(() => cfg.thrusterLeftCh, v => { draft.value.thrusterLeftCh = v; });
watch(() => cfg.thrusterRightCh, v => { draft.value.thrusterRightCh = v; });
watch(() => cfg.servoLeftCh, v => { draft.value.servoLeftCh = v; });
watch(() => cfg.servoRightCh, v => { draft.value.servoRightCh = v; });
watch(() => cfg.servoMethod, v => { draft.value.servoMethod = v; });

// Cek apakah draft berbeda dari store (ada perubahan belum disimpan)
const hasPendingChanges = computed(() =>
  draft.value.thrusterLeftCh !== cfg.thrusterLeftCh ||
  draft.value.thrusterRightCh !== cfg.thrusterRightCh ||
  draft.value.servoLeftCh !== cfg.servoLeftCh ||
  draft.value.servoRightCh !== cfg.servoRightCh ||
  draft.value.servoMethod !== cfg.servoMethod
);

// Status feedback
const applyStatus = ref(null); // null | 'success' | 'error'

function applyChanges() {
  if (ws.status !== 'CONNECTED') {
    applyStatus.value = 'error';
    setTimeout(() => (applyStatus.value = null), 3000);
    return;
  }
  // Update store dari draft
  cfg.thrusterLeftCh = draft.value.thrusterLeftCh;
  cfg.thrusterRightCh = draft.value.thrusterRightCh;
  cfg.servoLeftCh = draft.value.servoLeftCh;
  cfg.servoRightCh = draft.value.servoRightCh;
  cfg.servoMethod = draft.value.servoMethod;
  cfg.applyChannelMap();
  applyStatus.value = 'success';
  setTimeout(() => (applyStatus.value = null), 3000);
}

function resetDraft() {
  cfg.resetToDefault();
  draft.value = {
    thrusterLeftCh: cfg.thrusterLeftCh,
    thrusterRightCh: cfg.thrusterRightCh,
    servoLeftCh: cfg.servoLeftCh,
    servoRightCh: cfg.servoRightCh,
    servoMethod: cfg.servoMethod,
  };
}

function syncFromASV() {
  cfg.requestSync();
}

function channelLabel(ch) {
  return cfg.channelLabel(ch);
}

// Visual color untuk setiap channel group
function channelGroupClass(ch) {
  return ch <= 8
    ? 'bg-primary/10 text-primary border-primary/30'
    : 'bg-warning/10 text-warning border-warning/30';
}
</script>

<template>
  <div class="space-y-6">

    <!-- Header Info Banner -->
    <div class="glass-card p-5 border-l-4 border-l-primary">
      <h3 class="text-lg font-bold text-(--text-primary) flex items-center gap-2 mb-1">
        <Settings class="w-5 h-5 text-primary" />
        Channel Mapping — Thruster & Servo
      </h3>
      <p class="text-xs text-(--text-secondary) leading-relaxed">
        Atur channel RC Output Pixhawk untuk setiap aktuator. <span class="font-bold text-primary">MAIN 1–8</span>
        adalah konektor MAIN OUT, <span class="font-bold text-warning">AUX 1–8</span> adalah konektor AUX OUT.
        Perubahan dikirim langsung ke ASV via WebSocket dan berlaku seketika.
      </p>

      <!-- Sync Status -->
      <div class="flex items-center gap-3 mt-3">
        <div :class="['flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border',
          cfg.isSynced ? 'bg-success/10 text-success border-success/30' : 'bg-warning/10 text-warning border-warning/30']">
          <CheckCircle v-if="cfg.isSynced" class="w-3.5 h-3.5" />
          <AlertTriangle v-else class="w-3.5 h-3.5" />
          {{ cfg.isSynced ? `Synced with ASV — ${cfg.lastSyncTime}` : 'Not Synced' }}
        </div>

        <button @click="syncFromASV"
          :disabled="ws.status !== 'CONNECTED'"
          class="flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border
                 bg-(--bg-secondary) border-(--border-subtle) text-(--text-secondary)
                 hover:bg-white/10 hover:text-(--text-primary) transition-colors disabled:opacity-40 disabled:cursor-not-allowed">
          <RefreshCw class="w-3.5 h-3.5" />
          Sync from ASV
        </button>
      </div>
    </div>



    <!-- Channel Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">

      <!-- Thruster Kiri -->
      <div class="glass-card p-5 space-y-3">
        <div class="flex items-center gap-2">
          <div class="p-2 bg-sky-500/10 rounded-lg">
            <Zap class="w-4 h-4 text-sky-400" />
          </div>
          <div>
            <div class="text-sm font-bold text-(--text-primary)">Thruster Kiri</div>
            <div class="text-[10px] text-(--text-muted) uppercase tracking-wider">Left Motor / Port</div>
          </div>
          <span :class="['ml-auto text-xs font-mono font-bold px-2 py-1 rounded border', channelGroupClass(draft.thrusterLeftCh)]">
            {{ channelLabel(draft.thrusterLeftCh) }}
          </span>
        </div>
        <select v-model.number="draft.thrusterLeftCh"
          class="w-full bg-(--bg-secondary) border border-(--border-subtle) text-(--text-primary)
                 rounded-lg px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-primary transition-colors">
          <optgroup v-for="group in ['MAIN', 'AUX']" :key="group" :label="group">
            <option
              v-for="opt in cfg.channelOptions.filter(o => o.group === group)"
              :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </optgroup>
        </select>
      </div>

      <!-- Thruster Kanan -->
      <div class="glass-card p-5 space-y-3">
        <div class="flex items-center gap-2">
          <div class="p-2 bg-sky-500/10 rounded-lg">
            <Zap class="w-4 h-4 text-sky-400" />
          </div>
          <div>
            <div class="text-sm font-bold text-(--text-primary)">Thruster Kanan</div>
            <div class="text-[10px] text-(--text-muted) uppercase tracking-wider">Right Motor / Starboard</div>
          </div>
          <span :class="['ml-auto text-xs font-mono font-bold px-2 py-1 rounded border', channelGroupClass(draft.thrusterRightCh)]">
            {{ channelLabel(draft.thrusterRightCh) }}
          </span>
        </div>
        <select v-model.number="draft.thrusterRightCh"
          class="w-full bg-(--bg-secondary) border border-(--border-subtle) text-(--text-primary)
                 rounded-lg px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-primary transition-colors">
          <optgroup v-for="group in ['MAIN', 'AUX']" :key="group" :label="group">
            <option
              v-for="opt in cfg.channelOptions.filter(o => o.group === group)"
              :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </optgroup>
        </select>
      </div>

      <!-- Servo Kiri -->
      <div class="glass-card p-5 space-y-3">
        <div class="flex items-center gap-2">
          <div class="p-2 bg-purple-500/10 rounded-lg">
            <Navigation2 class="w-4 h-4 text-purple-400" />
          </div>
          <div>
            <div class="text-sm font-bold text-(--text-primary)">Servo Kiri</div>
            <div class="text-[10px] text-(--text-muted) uppercase tracking-wider">Left Vectoring / Azimuth</div>
          </div>
          <span :class="['ml-auto text-xs font-mono font-bold px-2 py-1 rounded border', channelGroupClass(draft.servoLeftCh)]">
            {{ channelLabel(draft.servoLeftCh) }}
          </span>
        </div>
        <select v-model.number="draft.servoLeftCh"
          class="w-full bg-(--bg-secondary) border border-(--border-subtle) text-(--text-primary)
                 rounded-lg px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-primary transition-colors">
          <optgroup v-for="group in ['MAIN', 'AUX']" :key="group" :label="group">
            <option
              v-for="opt in cfg.channelOptions.filter(o => o.group === group)"
              :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </optgroup>
        </select>
      </div>

      <!-- Servo Kanan -->
      <div class="glass-card p-5 space-y-3">
        <div class="flex items-center gap-2">
          <div class="p-2 bg-purple-500/10 rounded-lg">
            <Navigation2 class="w-4 h-4 text-purple-400" />
          </div>
          <div>
            <div class="text-sm font-bold text-(--text-primary)">Servo Kanan</div>
            <div class="text-[10px] text-(--text-muted) uppercase tracking-wider">Right Vectoring / Azimuth</div>
          </div>
          <span :class="['ml-auto text-xs font-mono font-bold px-2 py-1 rounded border', channelGroupClass(draft.servoRightCh)]">
            {{ channelLabel(draft.servoRightCh) }}
          </span>
        </div>
        <select v-model.number="draft.servoRightCh"
          class="w-full bg-(--bg-secondary) border border-(--border-subtle) text-(--text-primary)
                 rounded-lg px-3 py-2.5 text-sm font-mono focus:outline-none focus:border-primary transition-colors">
          <optgroup v-for="group in ['MAIN', 'AUX']" :key="group" :label="group">
            <option
              v-for="opt in cfg.channelOptions.filter(o => o.group === group)"
              :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </optgroup>
        </select>
      </div>
    </div>

    <!-- Channel Map Preview -->
    <div class="glass-card p-5">
      <div class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest mb-4">Preview Channel Assignment</div>
      <div class="grid grid-cols-9 gap-1.5">
        <template v-for="ch in 16" :key="ch">
          <div :class="[
            'rounded-lg p-2 text-center border text-[10px] font-mono font-bold transition-all',
            draft.thrusterLeftCh === ch ? 'bg-sky-500/20 border-sky-400 text-sky-300 scale-105' :
            draft.thrusterRightCh === ch ? 'bg-sky-500/20 border-sky-400 text-sky-300 scale-105' :
            draft.servoLeftCh === ch ? 'bg-purple-500/20 border-purple-400 text-purple-300 scale-105' :
            draft.servoRightCh === ch ? 'bg-purple-500/20 border-purple-400 text-purple-300 scale-105' :
            'bg-(--bg-secondary)/50 border-(--border-subtle)/30 text-(--text-muted)'
          ]">
            <div class="text-[8px] opacity-60 mb-0.5">{{ ch <= 8 ? 'M' : 'A' }}{{ ch <= 8 ? ch : ch - 8 }}</div>
            <div v-if="draft.thrusterLeftCh === ch">TL</div>
            <div v-else-if="draft.thrusterRightCh === ch">TR</div>
            <div v-else-if="draft.servoLeftCh === ch">SL</div>
            <div v-else-if="draft.servoRightCh === ch">SR</div>
            <div v-else class="opacity-30">—</div>
          </div>
        </template>
      </div>
      <div class="flex gap-4 mt-3 text-[10px] font-bold">
        <span class="flex items-center gap-1.5 text-sky-400"><span class="w-3 h-3 rounded bg-sky-500/20 border border-sky-400 inline-block"></span>Thruster (TL/TR)</span>
        <span class="flex items-center gap-1.5 text-purple-400"><span class="w-3 h-3 rounded bg-purple-500/20 border border-purple-400 inline-block"></span>Servo (SL/SR)</span>
      </div>
    </div>

    <!-- Action Buttons -->
    <div class="flex gap-3">
      <button @click="resetDraft"
        class="flex-1 py-3 rounded-xl font-bold text-sm border border-(--border-subtle)
               bg-(--bg-secondary) text-(--text-secondary) hover:bg-white/10 hover:text-(--text-primary) transition-all">
        Reset to Default
      </button>

      <button @click="applyChanges"
        :disabled="ws.status !== 'CONNECTED'"
        :class="[
          'flex-2 px-8 py-3 rounded-xl font-bold text-sm flex items-center justify-center gap-2 transition-all',
          hasPendingChanges && ws.status === 'CONNECTED'
            ? 'bg-primary text-slate-900 hover:brightness-110 shadow-lg shadow-primary/20'
            : 'bg-primary/40 text-slate-900/60 cursor-not-allowed',
          !hasPendingChanges && ws.status === 'CONNECTED' ? 'opacity-60' : ''
        ]">
        <Save class="w-4 h-4" />
        Apply to ASV
      </button>
    </div>

    <!-- Apply Status Feedback -->
    <transition name="fade">
      <div v-if="applyStatus"
        :class="[
          'p-4 rounded-xl border font-bold text-sm flex items-center gap-3',
          applyStatus === 'success'
            ? 'bg-success/10 border-success/30 text-success'
            : 'bg-danger/10 border-danger/30 text-danger'
        ]">
        <CheckCircle v-if="applyStatus === 'success'" class="w-5 h-5" />
        <AlertTriangle v-else class="w-5 h-5" />
        {{ applyStatus === 'success' ? 'Channel map berhasil dikirim ke ASV!' : 'Gagal: ASV tidak terkoneksi. Cek WebSocket.' }}
      </div>
    </transition>

  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
.flex-2 { flex: 2; }
</style>
