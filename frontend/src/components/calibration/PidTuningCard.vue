<script setup>
import { ref, onMounted } from 'vue';
import { Sliders, Save, CheckCircle2, RefreshCw } from 'lucide-vue-next';
import { useWebsocketStore } from '@/stores/websocketStore';
import { apiUrl } from '@/config/api';

const wsStore = useWebsocketStore();

// Dynamic state fetched from database
const kp = ref(0.04);
const ki = ref(0.001);
const kd = ref(0.008);
const forwardSpeed = ref(0.4);
const maxTurnRate = ref(15.0);
const alignThresholdPx = ref(40.0);

const statusMsg = ref('');
const isSaved = ref(false);

const loadFromDatabase = async () => {
  try {
    const res = await fetch(apiUrl('/api/v1/pid-config'));
    if (res.ok) {
      const result = await res.json();
      if (result.data) {
        if (result.data.kp !== undefined) kp.value = result.data.kp;
        if (result.data.ki !== undefined) ki.value = result.data.ki;
        if (result.data.kd !== undefined) kd.value = result.data.kd;
        if (result.data.forward_speed !== undefined) forwardSpeed.value = result.data.forward_speed;
        if (result.data.max_turn_rate !== undefined) maxTurnRate.value = result.data.max_turn_rate;
        if (result.data.align_threshold_px !== undefined) alignThresholdPx.value = result.data.align_threshold_px;
      }
    }
  } catch (err) {
    console.error('Failed to load PID config from DB:', err);
  }
};

onMounted(() => {
  loadFromDatabase();
});

const applyTuning = async () => {
  // 1. Broadcast live via WebSocket to ASV
  wsStore.updatePid({
    kp: kp.value,
    ki: ki.value,
    kd: kd.value,
    forward_speed: forwardSpeed.value,
    max_turn_rate: maxTurnRate.value,
    align_threshold_px: alignThresholdPx.value
  });

  // 2. Persist in Database via HTTP REST API
  try {
    await fetch(apiUrl('/api/v1/pid-config'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kp: kp.value,
        ki: ki.value,
        kd: kd.value,
        forward_speed: forwardSpeed.value,
        max_turn_rate: maxTurnRate.value,
        align_threshold_px: alignThresholdPx.value
      })
    });
  } catch (e) {
    console.error('Failed to persist PID in database:', e);
  }
  
  isSaved.value = true;
  statusMsg.value = `Applied & Saved to DB: Kp=${kp.value}, Ki=${ki.value}, Kd=${kd.value}, Speed=${forwardSpeed.value}m/s, MaxTurn=${maxTurnRate.value}°/s`;
  setTimeout(() => { isSaved.value = false; }, 3000);
};

const resetDefaults = () => {
  kp.value = 0.04;
  ki.value = 0.001;
  kd.value = 0.008;
  forwardSpeed.value = 0.4;
  maxTurnRate.value = 15.0;
  alignThresholdPx.value = 40.0;
  applyTuning();
};
</script>


<template>
  <div class="glass-card p-6 space-y-6">
    <div class="flex justify-between items-center border-b border-(--border-subtle) pb-4">
       <div class="flex items-center gap-3">
          <Sliders class="w-5 h-5 text-primary" />
          <div>
             <h2 class="text-sm font-black text-(--text-primary) uppercase tracking-widest">AI Vision PID Tuning</h2>
             <p class="text-[10px] text-(--text-secondary) font-bold uppercase">Real-Time Steering & Speed Controller Adjustment</p>
          </div>
       </div>
       <button @click="resetDefaults" class="text-[10px] font-bold text-(--text-secondary) hover:text-(--text-primary) uppercase flex items-center gap-1">
          <RefreshCw class="w-3 h-3" /> Reset Defaults
       </button>
    </div>

    <!-- PID Controls Grid -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
       <!-- Kp -->
       <div class="space-y-2 bg-(--bg-secondary) p-4 rounded-xl border border-(--border-primary)">
          <div class="flex justify-between items-center text-[10px] font-black uppercase">
             <span class="text-primary">Kp (Proportional)</span>
             <span class="font-mono text-sm text-(--text-primary)">{{ kp.toFixed(3) }}</span>
          </div>
          <input type="range" min="0.001" max="0.500" step="0.001" v-model.number="kp" class="w-full accent-primary cursor-pointer" />
          <input type="number" step="0.001" v-model.number="kp" class="w-full bg-card border border-(--border-subtle) rounded px-2 py-1 text-xs font-mono text-(--text-primary)" />
       </div>

       <!-- Ki -->
       <div class="space-y-2 bg-(--bg-secondary) p-4 rounded-xl border border-(--border-primary)">
          <div class="flex justify-between items-center text-[10px] font-black uppercase">
             <span class="text-warning">Ki (Integral)</span>
             <span class="font-mono text-sm text-(--text-primary)">{{ ki }}</span>
          </div>
          <input type="range" min="0" max="5" step="0.0001" v-model.number="ki" class="w-full accent-warning cursor-pointer" />
          <input type="number" step="0.0001" v-model.number="ki" class="w-full bg-card border border-(--border-subtle) rounded px-2 py-1 text-xs font-mono text-(--text-primary)" />
       </div>

       <!-- Kd -->
       <div class="space-y-2 bg-(--bg-secondary) p-4 rounded-xl border border-(--border-primary)">
          <div class="flex justify-between items-center text-[10px] font-black uppercase">
             <span class="text-success">Kd (Derivative)</span>
             <span class="font-mono text-sm text-(--text-primary)">{{ kd }}</span>
          </div>
          <input type="range" min="0" max="10" step="0.001" v-model.number="kd" class="w-full accent-success cursor-pointer" />
          <input type="number" step="0.001" v-model.number="kd" class="w-full bg-card border border-(--border-subtle) rounded px-2 py-1 text-xs font-mono text-(--text-primary)" />
       </div>
    </div>

    <!-- Secondary Parameters Grid -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
       <!-- Max Throttle Scale / Forward Speed -->
       <div class="space-y-2 bg-(--bg-secondary) p-4 rounded-xl border border-(--border-primary)">
          <div class="flex justify-between items-center text-[10px] font-black uppercase">
             <span class="text-(--text-secondary)">Max Throttle Scale (%) / Speed</span>
             <span class="font-mono text-sm text-primary">{{ forwardSpeed <= 1.0 ? Math.round(forwardSpeed * 100) + '%' : forwardSpeed.toFixed(1) + ' m/s' }}</span>
          </div>
          <input type="range" min="0.05" max="1.0" step="0.01" v-model.number="forwardSpeed" class="w-full accent-primary cursor-pointer" />
       </div>

       <!-- Max Turn Rate Limit -->
       <div class="space-y-2 bg-(--bg-secondary) p-4 rounded-xl border border-(--border-primary)">
          <div class="flex justify-between items-center text-[10px] font-black uppercase">
             <span class="text-(--text-secondary)">Max Turn Rate (°/s)</span>
             <span class="font-mono text-sm text-primary">{{ maxTurnRate }} °/s</span>
          </div>
          <input type="range" min="5" max="60" step="1" v-model.number="maxTurnRate" class="w-full accent-primary cursor-pointer" />
       </div>

       <!-- Align Tolerance -->
       <div class="space-y-2 bg-(--bg-secondary) p-4 rounded-xl border border-(--border-primary)">
          <div class="flex justify-between items-center text-[10px] font-black uppercase">
             <span class="text-(--text-secondary)">Align Tolerance (Pixels)</span>
             <span class="font-mono text-sm text-primary">{{ alignThresholdPx }} px</span>
          </div>
          <input type="range" min="15" max="100" step="1" v-model.number="alignThresholdPx" class="w-full accent-primary cursor-pointer" />
       </div>
    </div>

    <!-- Action Button -->
    <div class="flex items-center justify-between pt-2">
       <div v-if="statusMsg" class="text-xs font-bold text-success flex items-center gap-2">
          <CheckCircle2 class="w-4 h-4" /> {{ statusMsg }}
       </div>
       <div v-else></div>

       <button 
          @click="applyTuning"
          class="bg-primary hover:bg-red-600 text-slate-900 font-black px-6 py-3 rounded-xl text-xs uppercase tracking-widest flex items-center gap-2 transition-all shadow-lg shadow-primary/20"
       >
          <Save class="w-4 h-4" /> Apply PID Tuning Live
       </button>
    </div>
  </div>
</template>
