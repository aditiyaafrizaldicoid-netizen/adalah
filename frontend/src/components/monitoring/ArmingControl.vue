<script setup>
import { ref, computed, watch } from 'vue';
import { Shield, ShieldOff, AlertTriangle, Loader2 } from 'lucide-vue-next';
import { useWebsocketStore } from '@/stores/websocketStore';
import { useVesselStore } from '@/stores/vesselStore';

const ws = useWebsocketStore();
const vessel = useVesselStore();

const isLoading = ref(false);
const loadingTimeout = ref(null);
const showDisarmConfirm = ref(false);

const isConnected = computed(() => ws.status === 'CONNECTED');
const isArmed = computed(() => vessel.isArmed);
const fcConnected = computed(() => vessel.isConnected);

function startLoading() {
  isLoading.value = true;
  if (loadingTimeout.value) clearTimeout(loadingTimeout.value);
  loadingTimeout.value = setTimeout(() => { isLoading.value = false; }, 4000);
}

function arm() {
  if (!isConnected.value || !fcConnected.value) return;
  startLoading();
  ws.sendCommand({ action: 'arm' });
}

function disarm() {
  showDisarmConfirm.value = false;
  if (!isConnected.value) return;
  startLoading();
  ws.sendCommand({ action: 'disarm' });
}

function setMode(mode) {
  if (!isConnected.value) return;
  ws.sendCommand({ action: 'set_mode', mode });
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

    <!-- ARM Button -->
    <div v-if="!isArmed">
      <button
        @click="arm()"
        :disabled="!isConnected || !fcConnected || isLoading"
        class="w-full py-2.5 rounded-xl font-black text-sm flex items-center justify-center gap-2
               transition-all border border-success/40 bg-success/10 text-success
               hover:bg-success/20 hover:border-success/70 active:scale-95
               disabled:opacity-40 disabled:cursor-not-allowed">
        <Loader2 v-if="isLoading" class="w-4 h-4 animate-spin" />
        <Shield v-else class="w-4 h-4" />
        ARM
      </button>
    </div>

    <!-- DISARM Button -->
    <div v-else>
      <button
        v-if="!showDisarmConfirm"
        @click="showDisarmConfirm = true"
        :disabled="!isConnected || isLoading"
        class="w-full py-2.5 rounded-xl font-black text-sm flex items-center justify-center gap-2
               transition-all border border-danger/40 bg-danger/10 text-danger
               hover:bg-danger/20 hover:border-danger/70 active:scale-95
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
        <button @click="disarm()"
          class="flex-1 py-2.5 rounded-xl font-black text-xs border border-danger/40
                 bg-danger/10 text-danger hover:bg-danger/20 transition-all flex items-center justify-center gap-1">
          <AlertTriangle class="w-3.5 h-3.5" />
          Yakin Disarm
        </button>
      </div>
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
