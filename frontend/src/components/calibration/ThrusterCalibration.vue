<script setup>
import { Zap, SlidersHorizontal, Send, AlertTriangle } from 'lucide-vue-next';
import { ref } from 'vue';
import { useWebsocketStore } from '@/stores/websocketStore';

const ws = useWebsocketStore();

const thrusterL = ref(0);
const thrusterR = ref(0);
const trimPort = ref(0);      // -100 to +100 percent offset
const trimStarboard = ref(0);
const testStatus = ref(null); // null | 'ok' | 'err' | 'warning'

// Mapping slider % (0-100) ke MAVLink z (0-1000)
function pctToZ(pct) { return Math.round(pct * 10); }

function sendThrusterTest() {
  if (ws.status !== 'CONNECTED') {
    testStatus.value = 'err';
    setTimeout(() => { testStatus.value = null; }, 3000);
    return;
  }
  // Kirim sebagai manual_control: x=0 (no pitch), y=0 (no roll), z=throttle, r=0 (no yaw)
  // Nilai z adalah rata-rata L+R dengan offset trim
  const z = Math.round((pctToZ(thrusterL.value) + pctToZ(thrusterR.value)) / 2);
  ws.sendCommand({
    action: 'manual_control',
    x: 0,
    y: 0,
    z: Math.max(0, Math.min(1000, z)),
    r: Math.round((thrusterL.value - thrusterR.value) * 5), // differential steering
    buttons: 0
  });
  testStatus.value = 'ok';
  setTimeout(() => { testStatus.value = null; }, 2000);
}

function stopTest() {
  thrusterL.value = 0;
  thrusterR.value = 0;
  ws.sendCommand({ action: 'manual_control', x: 0, y: 0, z: 0, r: 0, buttons: 0 });
  testStatus.value = null;
}

function applyTrim() {
  if (ws.status !== 'CONNECTED') return;
  ws.sendCommand({
    action: 'set_thruster_trim',
    port_offset: trimPort.value / 100,
    starboard_offset: trimStarboard.value / 100,
  });
}
</script>

<template>
  <div class="space-y-6">
    <!-- Safety Warning -->
    <div class="flex items-start gap-3 p-4 bg-warning/10 border border-warning/30 rounded-xl text-xs text-warning font-bold">
      <AlertTriangle class="w-4 h-4 flex-shrink-0 mt-0.5" />
      <span>Pastikan kapal berada di atas dudukan / stand sebelum melakukan tes thruster. Motor akan berputar!</span>
    </div>

    <!-- Thruster Level Sliders -->
    <div class="grid grid-cols-2 gap-6">
      <div v-for="(side, i) in ['Left', 'Right']" :key="side" class="glass-card p-6 flex flex-col items-center">
        <span class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest mb-6">{{ side }} Thruster Test</span>
        <div class="h-48 w-8 bg-(--bg-secondary) rounded-full relative overflow-hidden border border-(--border-primary)">
          <div class="absolute bottom-0 w-full bg-primary transition-all duration-150"
            :style="{ height: `${i === 0 ? thrusterL : thrusterR}%` }"></div>
        </div>
        <div class="mt-4 text-xl font-black text-(--text-primary) font-mono">
          {{ i === 0 ? thrusterL : thrusterR }}%
        </div>
        <input :value="i === 0 ? thrusterL : thrusterR"
          @input="e => i === 0 ? thrusterL = Number(e.target.value) : thrusterR = Number(e.target.value)"
          type="range" min="0" max="100" step="1"
          class="mt-4 w-full accent-primary cursor-pointer" />
      </div>
    </div>

    <!-- Test Action Buttons -->
    <div class="flex gap-3">
      <button @click="sendThrusterTest" :disabled="ws.status !== 'CONNECTED' || (thrusterL === 0 && thrusterR === 0)"
        :class="['flex-1 py-3 rounded-xl text-xs font-black uppercase flex items-center justify-center gap-2 transition-all',
          testStatus === 'ok' ? 'bg-success text-slate-900' : testStatus === 'err' ? 'bg-danger text-white' : 'bg-primary text-slate-900 hover:brightness-110',
          'disabled:opacity-40 disabled:cursor-not-allowed']">
        <Send class="w-4 h-4" />
        {{ testStatus === 'ok' ? 'DIKIRIM!' : testStatus === 'err' ? 'GAGAL' : 'SEND THRUST TEST' }}
      </button>
      <button @click="stopTest" :disabled="ws.status !== 'CONNECTED'"
        class="flex-1 py-3 bg-card text-(--text-primary) rounded-xl text-xs font-black uppercase border border-(--border-subtle) hover:bg-danger/20 hover:text-danger hover:border-danger/30 transition-all disabled:opacity-40">
        STOP (0%)
      </button>
    </div>

    <!-- Trim & Balance -->
    <div class="glass-card p-6 border-l-4 border-l-warning">
      <div class="flex items-center gap-3 mb-6">
        <SlidersHorizontal class="w-5 h-5 text-warning" />
        <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Trim & Balance Adjustment</span>
      </div>

      <div class="space-y-6 max-w-md">
        <div class="flex items-center gap-6">
          <span class="text-[10px] font-bold text-(--text-secondary) uppercase w-28">Port Offset</span>
          <input v-model.number="trimPort" type="range" min="-20" max="20" step="1"
            class="flex-1 accent-warning cursor-pointer" />
          <span class="text-xs font-mono text-warning w-14">{{ trimPort > 0 ? '+' : '' }}{{ trimPort }}%</span>
        </div>
        <div class="flex items-center gap-6">
          <span class="text-[10px] font-bold text-(--text-secondary) uppercase w-28">Starboard Offset</span>
          <input v-model.number="trimStarboard" type="range" min="-20" max="20" step="1"
            class="flex-1 accent-warning cursor-pointer" />
          <span class="text-xs font-mono text-warning w-14">{{ trimStarboard > 0 ? '+' : '' }}{{ trimStarboard }}%</span>
        </div>
      </div>

      <button @click="applyTrim" :disabled="ws.status !== 'CONNECTED'"
        class="mt-4 px-6 py-2.5 bg-warning text-slate-900 rounded-xl text-xs font-black uppercase transition-all disabled:opacity-40">
        Apply Trim to ASV
      </button>
    </div>
  </div>
</template>
