<script setup>
import { ref, computed, watch } from 'vue';
import { Shield, ShieldOff, AlertTriangle, Loader2, Zap, Info, CheckCircle, RotateCcw } from 'lucide-vue-next';
import { useWebsocketStore } from '@/stores/websocketStore';
import { useVesselStore } from '@/stores/vesselStore';

const ws = useWebsocketStore();
const vessel = useVesselStore();

const isLoading = ref(false);
const loadingTimeout = ref(null);
const showDisarmConfirm = ref(false);
const showForceDisarmConfirm = ref(false);
const showParamPanel = ref(false);
const paramStatus = ref(null); // null | 'applying' | 'success' | 'restored'

const isConnected = computed(() => ws.status === 'CONNECTED');
const isArmed = computed(() => vessel.isArmed);
const fcConnected = computed(() => vessel.isConnected);
// Mode otonom yang memblok disarm biasa di ArduPilot
const isAutonomousMode = computed(() =>
  ['GUIDED', 'AUTO', 'RTL', 'CIRCLE', 'LOITER'].includes(vessel.mode?.toUpperCase())
);

function startLoading() {
  isLoading.value = true;
  if (loadingTimeout.value) clearTimeout(loadingTimeout.value);
  loadingTimeout.value = setTimeout(() => { isLoading.value = false; }, 4000);
}

function arm(force = false) {
  if (!isConnected.value || !fcConnected.value) return;
  startLoading();
  ws.sendCommand({ action: 'arm', force });
}

function disarm(force = false) {
  showDisarmConfirm.value = false;
  if (!isConnected.value) return;
  startLoading();
  ws.sendCommand({ action: 'disarm', force });
}

function forceDisarm() {
  showDisarmConfirm.value = false;
  showForceDisarmConfirm.value = false;
  if (!isConnected.value) return;
  startLoading();
  ws.sendCommand({ action: 'disarm', force: true });
}

function setMode(mode) {
  if (!isConnected.value) return;
  ws.sendCommand({ action: 'set_mode', mode });
}

function applyNoRcMode() {
  if (!isConnected.value || !fcConnected.value) return;
  paramStatus.value = 'applying';
  ws.sendCommand({ action: 'apply_no_rc_mode' });
  // Auto-clear setelah 3 detik (konfirmasi datang via PARAM_SET_RESULT)
  setTimeout(() => {
    if (paramStatus.value === 'applying') paramStatus.value = 'success';
  }, 1500);
}

function restoreFailsafe() {
  if (!isConnected.value || !fcConnected.value) return;
  paramStatus.value = 'applying';
  ws.sendCommand({ action: 'restore_failsafe' });
  setTimeout(() => {
    if (paramStatus.value === 'applying') paramStatus.value = 'restored';
  }, 1500);
}

// Reset loading saat state berubah dari telemetri
watch(() => vessel.isArmed, () => {
  isLoading.value = false;
  if (loadingTimeout.value) clearTimeout(loadingTimeout.value);
});
</script>

<template>
  <div class="glass-card p-5 flex flex-col gap-4">

    <!-- Header -->
    <div class="flex items-center justify-between">
      <span class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest">
        Flight Controller
      </span>
      <div :class="[
        'flex items-center gap-1.5 text-[10px] font-bold px-2 py-1 rounded-full border',
        fcConnected
          ? 'bg-success/10 text-success border-success/30'
          : 'bg-danger/10 text-danger border-danger/30'
      ]">
        <div :class="['w-1.5 h-1.5 rounded-full', fcConnected ? 'bg-success animate-pulse' : 'bg-danger']"></div>
        {{ fcConnected ? 'FC ONLINE' : 'FC OFFLINE' }}
      </div>
    </div>

    <!-- ARM Status Display -->
    <div :class="[
      'flex items-center gap-4 p-4 rounded-xl border transition-all duration-300',
      isArmed
        ? 'bg-danger/10 border-danger/30'
        : 'bg-(--bg-secondary)/50 border-(--border-subtle)/50'
    ]">
      <div :class="['p-3 rounded-xl transition-all', isArmed ? 'bg-danger/20' : 'bg-(--bg-secondary)']">
        <Shield v-if="isArmed" class="w-6 h-6 text-danger" />
        <ShieldOff v-else class="w-6 h-6 text-(--text-muted)" />
      </div>
      <div>
        <div :class="['text-xl font-black tracking-widest', isArmed ? 'text-danger' : 'text-(--text-secondary)']">
          {{ isArmed ? 'ARMED' : 'DISARMED' }}
        </div>
        <div class="text-[10px] text-(--text-muted) uppercase tracking-wider mt-0.5">
          Mode: <span class="font-bold text-(--text-secondary)">{{ vessel.mode }}</span>
        </div>
      </div>
      <div v-if="isArmed" class="ml-auto">
        <div class="w-3 h-3 rounded-full bg-danger animate-ping"></div>
      </div>
    </div>

    <!-- ARM Buttons -->
    <div class="flex gap-2" v-if="!isArmed">
      <!-- Normal ARM -->
      <button
        @click="arm(false)"
        :disabled="!isConnected || !fcConnected || isLoading"
        class="flex-1 py-2.5 rounded-xl font-black text-sm flex items-center justify-center gap-2
               transition-all border border-success/40 bg-success/10 text-success
               hover:bg-success/20 hover:border-success/70 active:scale-95
               disabled:opacity-40 disabled:cursor-not-allowed">
        <Loader2 v-if="isLoading" class="w-4 h-4 animate-spin" />
        <Shield v-else class="w-4 h-4" />
        ARM
      </button>

      <!-- FORCE ARM -->
      <button
        @click="arm(true)"
        :disabled="!isConnected || !fcConnected || isLoading"
        title="Force ARM: bypass semua pre-arm checks (RC Failsafe, GPS, dll)"
        class="flex-1 py-2.5 rounded-xl font-black text-sm flex items-center justify-center gap-2
               transition-all border border-danger/40 bg-danger/10 text-danger
               hover:bg-danger/20 hover:border-danger/70 active:scale-95
               disabled:opacity-40 disabled:cursor-not-allowed">
        <Zap class="w-4 h-4" />
        FORCE ARM
      </button>
    </div>

    <!-- DISARM Buttons -->
    <template v-if="isArmed">
      <!-- Warning banner: mode otonom aktif -->
      <div v-if="isAutonomousMode"
        class="p-3 rounded-xl border border-warning/40 bg-warning/10 flex flex-col gap-2">
        <div class="flex items-center gap-2">
          <AlertTriangle class="w-4 h-4 text-warning shrink-0 animate-pulse" />
          <span class="text-[10px] font-black text-warning uppercase tracking-wider">
            Mode {{ vessel.mode }} Aktif!
          </span>
        </div>
        <p class="text-[10px] text-(--text-muted) leading-relaxed">
          ArduPilot memblok disarm biasa saat mode otonom. Ganti ke MANUAL atau gunakan
          <b class="text-danger">FORCE DISARM</b>.
        </p>
        <!-- Force Disarm Confirm -->
        <div v-if="!showForceDisarmConfirm">
          <button
            @click="showForceDisarmConfirm = true"
            :disabled="!isConnected || isLoading"
            class="w-full py-2 rounded-lg font-black text-xs flex items-center justify-center gap-2
                   transition-all border border-danger/50 bg-danger/15 text-danger
                   hover:bg-danger/30 active:scale-95
                   disabled:opacity-40 disabled:cursor-not-allowed">
            <Loader2 v-if="isLoading" class="w-3.5 h-3.5 animate-spin" />
            <ShieldOff v-else class="w-3.5 h-3.5" />
            FORCE DISARM
          </button>
        </div>
        <div v-else class="flex gap-2">
          <button @click="showForceDisarmConfirm = false"
            class="flex-1 py-2 rounded-lg font-bold text-[10px] border border-(--border-subtle)
                   bg-(--bg-secondary) text-(--text-secondary) hover:bg-white/10 transition-all">
            Batal
          </button>
          <button @click="forceDisarm()"
            class="flex-1 py-2 rounded-lg font-black text-[10px] border border-danger/60
                   bg-danger/20 text-danger hover:bg-danger/40 transition-all flex items-center justify-center gap-1 animate-pulse">
            <AlertTriangle class="w-3 h-3" />
            Konfirmasi FORCE DISARM
          </button>
        </div>
      </div>

      <!-- Normal disarm (mode bukan otonom) -->
      <template v-else>
        <button
          v-if="!showDisarmConfirm"
          @click="showDisarmConfirm = true"
          :disabled="!isConnected || isLoading"
          class="w-full py-2.5 rounded-xl font-black text-sm flex items-center justify-center gap-2
                 transition-all border border-(--border-subtle) bg-(--bg-secondary)
                 text-(--text-secondary) hover:bg-white/10 hover:text-(--text-primary) active:scale-95
                 disabled:opacity-40 disabled:cursor-not-allowed">
          <Loader2 v-if="isLoading" class="w-4 h-4 animate-spin" />
          <ShieldOff v-else class="w-4 h-4" />
          DISARM
        </button>
        <div v-else class="flex gap-2">
          <button @click="showDisarmConfirm = false"
            class="flex-1 py-2.5 rounded-xl font-bold text-xs border border-(--border-subtle)
                   bg-(--bg-secondary) text-(--text-secondary) hover:bg-white/10 transition-all">
            Batal
          </button>
          <button @click="disarm(false)"
            class="flex-1 py-2.5 rounded-xl font-black text-xs border border-warning/40
                   bg-warning/10 text-warning hover:bg-warning/20 transition-all flex items-center justify-center gap-1">
            <AlertTriangle class="w-3.5 h-3.5" />
            Yakin Disarm
          </button>
        </div>
      </template>
    </template>

    <!-- No-RC Mode Panel -->
    <div class="rounded-xl border border-(--border-subtle)/50 bg-(--bg-secondary)/30 overflow-hidden">
      <button
        @click="showParamPanel = !showParamPanel"
        class="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-white/5 transition-colors">
        <Info class="w-3.5 h-3.5 text-warning shrink-0" />
        <span class="text-[10px] font-bold text-warning uppercase tracking-wider flex-1">
          Tanpa RC Receiver
        </span>
        <span class="text-[10px] text-(--text-muted)">{{ showParamPanel ? '▲' : '▼' }}</span>
      </button>

      <transition name="slide">
        <div v-if="showParamPanel" class="px-4 pb-4 space-y-3">
          <p class="text-[10px] text-(--text-secondary) leading-relaxed">
            Kirim parameter langsung ke Pixhawk untuk <b class="text-warning">disable RC Failsafe</b>
            agar bisa ARM dan kontrol servo tanpa RC receiver fisik.
          </p>

          <!-- Apply No-RC Mode Button -->
          <button
            @click="applyNoRcMode"
            :disabled="!isConnected || !fcConnected || paramStatus === 'applying'"
            class="w-full py-2.5 rounded-lg font-bold text-xs flex items-center justify-center gap-2
                   border border-warning/40 bg-warning/10 text-warning
                   hover:bg-warning/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed">
            <Loader2 v-if="paramStatus === 'applying'" class="w-3.5 h-3.5 animate-spin" />
            <Zap v-else class="w-3.5 h-3.5" />
            Apply No-RC Mode & RCPassThru
            <span class="text-[9px] opacity-60">(FS_THR=0, SERVOx_FUNC=1)</span>
          </button>

          <!-- Status feedback -->
          <transition name="fade">
            <div v-if="paramStatus === 'success'"
              class="flex items-center gap-2 p-2.5 rounded-lg bg-success/10 border border-success/30 text-success text-[10px] font-bold">
              <CheckCircle class="w-3.5 h-3.5" />
              Parameter berhasil dikirim ke Pixhawk! Sekarang coba FORCE ARM.
            </div>
            <div v-else-if="paramStatus === 'restored'"
              class="flex items-center gap-2 p-2.5 rounded-lg bg-primary/10 border border-primary/30 text-primary text-[10px] font-bold">
              <CheckCircle class="w-3.5 h-3.5" />
              Failsafe dikembalikan ke default.
            </div>
          </transition>

          <!-- Restore Button -->
          <button
            @click="restoreFailsafe"
            :disabled="!isConnected || !fcConnected || paramStatus === 'applying'"
            class="w-full py-2 rounded-lg font-bold text-[10px] flex items-center justify-center gap-2
                   border border-(--border-subtle)/50 bg-(--bg-secondary)/50 text-(--text-muted)
                   hover:text-(--text-secondary) hover:bg-(--bg-secondary) transition-all disabled:opacity-40">
            <RotateCcw class="w-3 h-3" />
            Restore Failsafe Default
          </button>

          <p class="text-[9px] text-(--text-muted) italic">
            ⚠️ Untuk testing saja. Restore sebelum deploy di lapangan.
          </p>
        </div>
      </transition>
    </div>

    <!-- Mode Quick-Set -->
    <div>
      <div class="text-[10px] font-bold text-(--text-muted) uppercase tracking-widest mb-2">Quick Mode</div>
      <div class="grid grid-cols-3 gap-1.5">
        <button
          v-for="m in ['MANUAL', 'HOLD', 'GUIDED']"
          :key="m"
          @click="setMode(m)"
          :disabled="!isConnected || !fcConnected"
          :class="[
            'py-1.5 rounded-lg text-[10px] font-black tracking-wider border transition-all',
            'disabled:opacity-40 disabled:cursor-not-allowed',
            vessel.mode === m
              ? 'bg-primary text-slate-900 border-primary'
              : 'bg-(--bg-secondary) text-(--text-secondary) border-(--border-subtle)/50 hover:bg-white/10 hover:text-(--text-primary)'
          ]">
          {{ m }}
        </button>
      </div>
    </div>

  </div>
</template>

<style scoped>
.slide-enter-active, .slide-leave-active {
  transition: all 0.25s ease;
  overflow: hidden;
}
.slide-enter-from, .slide-leave-to {
  max-height: 0;
  opacity: 0;
}
.slide-enter-to, .slide-leave-from {
  max-height: 400px;
  opacity: 1;
}
</style>
