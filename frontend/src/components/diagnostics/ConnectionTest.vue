<script setup>
import { Wifi, RefreshCw, Send } from 'lucide-vue-next';
import { ref, computed } from 'vue';
import { useWebsocketStore } from '@/stores/websocketStore';
import { useChannelConfigStore } from '@/stores/channelConfigStore';

const wsStore = useWebsocketStore();
const cfg = useChannelConfigStore();
const isTesting = ref(false);
const pingHistory = ref([]);

const latency = computed(() => wsStore.latency || 0);
const avgLatency = computed(() => {
  if (!pingHistory.value.length) return latency.value;
  return Math.round(pingHistory.value.reduce((a, b) => a + b, 0) / pingHistory.value.length);
});

function runTest() {
  if (wsStore.status !== 'CONNECTED') return;
  isTesting.value = true;
  // Kirim PING dan catat latency berikutnya
  const before = Date.now();
  wsStore.sendCommand({ action: 'get_mission_status' }); // pancing respons
  setTimeout(() => {
    pingHistory.value.push(wsStore.latency);
    if (pingHistory.value.length > 5) pingHistory.value.shift();
    isTesting.value = false;
  }, 600);
}

function forceSync() {
  if (wsStore.status !== 'CONNECTED') return;
  cfg.requestSync();
  wsStore.sendCommand({ action: 'get_mission_status' });
}
</script>

<template>
  <div class="glass-card p-6 flex flex-col gap-6">
    <div class="flex items-center gap-3">
      <Wifi class="w-5 h-5 text-primary" />
      <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Connection Diagnostics</span>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <div class="p-6 bg-(--bg-secondary) rounded-2xl border border-(--border-primary) text-center relative overflow-hidden">
        <span class="text-[10px] text-(--text-secondary) font-bold uppercase block mb-1">Latency (Ping)</span>
        <span class="text-3xl font-black text-(--text-primary) font-mono">{{ latency }}<span class="text-xs text-primary">ms</span></span>
        <div class="text-[9px] text-(--text-muted) mt-1">Avg: {{ avgLatency }}ms</div>
        <div v-if="isTesting" class="absolute inset-0 bg-primary/10 flex items-center justify-center backdrop-blur-sm">
          <RefreshCw class="w-6 h-6 text-primary animate-spin" />
        </div>
      </div>
      <div class="p-6 bg-(--bg-secondary) rounded-2xl border border-(--border-primary) text-center">
        <span class="text-[10px] text-(--text-secondary) font-bold uppercase block mb-1">WS Status</span>
        <span class="text-xl font-black font-mono"
          :class="wsStore.status === 'CONNECTED' ? 'text-success' : wsStore.status === 'CONNECTING' ? 'text-warning' : 'text-danger'">
          {{ wsStore.status }}
        </span>
      </div>
    </div>

    <div class="flex gap-2">
      <button @click="runTest" :disabled="wsStore.status !== 'CONNECTED'"
        class="flex-1 py-3 bg-card hover:bg-(--bg-secondary) text-(--text-primary) rounded-xl text-[10px] font-bold uppercase transition-all flex items-center justify-center gap-2 disabled:opacity-40">
        <RefreshCw class="w-3.5 h-3.5" /> Link Test
      </button>
      <button @click="forceSync" :disabled="wsStore.status !== 'CONNECTED'"
        class="flex-1 py-3 bg-primary text-slate-900 rounded-xl text-[10px] font-black uppercase transition-all flex items-center justify-center gap-2 disabled:opacity-40">
        <Send class="w-3.5 h-3.5" /> Force Sync
      </button>
    </div>
  </div>
</template>
