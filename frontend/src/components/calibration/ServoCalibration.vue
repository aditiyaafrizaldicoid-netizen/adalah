<script setup>
import { ref, computed } from 'vue';
import { Settings, Play, Square, Zap, Navigation2, AlertTriangle, RefreshCw } from 'lucide-vue-next';
import { useWebsocketStore } from '@/stores/websocketStore';
import { useChannelConfigStore } from '@/stores/channelConfigStore';
import { useVesselStore } from '@/stores/vesselStore';

const ws = useWebsocketStore();
const cfg = useChannelConfigStore();
const vessel = useVesselStore();

/**
 * Daftar aktuator diambil secara DINAMIS dari channelConfigStore.
 * Channel akan otomatis update jika user mengubah channel map.
 */
const actuators = computed(() => [
  {
    id: 'thruster_left',
    name: 'Thruster Kiri',
    role: 'TL',
    icon: Zap,
    color: 'sky',
    channel: cfg.thrusterLeftCh,
    label: cfg.thrusterLeftLabel,
    pwm: 1500,
    min: 1000,
    max: 2000,
    center: 1500,
    isTesting: false,
    description: 'Motor kiri / Port Thruster',
  },
  {
    id: 'thruster_right',
    name: 'Thruster Kanan',
    role: 'TR',
    icon: Zap,
    color: 'sky',
    channel: cfg.thrusterRightCh,
    label: cfg.thrusterRightLabel,
    pwm: 1500,
    min: 1000,
    max: 2000,
    center: 1500,
    isTesting: false,
    description: 'Motor kanan / Starboard Thruster',
  },
  {
    id: 'servo_left',
    name: 'Servo Kiri',
    role: 'SL',
    icon: Navigation2,
    color: 'purple',
    channel: cfg.servoLeftCh,
    label: cfg.servoLeftLabel,
    pwm: 1500,
    min: 1000,
    max: 2000,
    center: 1500,
    isTesting: false,
    description: 'Arah thruster kiri / Vectoring kiri',
  },
  {
    id: 'servo_right',
    name: 'Servo Kanan',
    role: 'SR',
    icon: Navigation2,
    color: 'purple',
    channel: cfg.servoRightCh,
    label: cfg.servoRightLabel,
    pwm: 1500,
    min: 1000,
    max: 2000,
    center: 1500,
    isTesting: false,
    description: 'Arah thruster kanan / Vectoring kanan',
  },
]);

// State PWM mutable per aktuator (keluarkan dari computed agar bisa diubah)
const pwmState = ref({
  thruster_left: 1500,
  thruster_right: 1500,
  servo_left: 1500,
  servo_right: 1500,
});

const testingState = ref({
  thruster_left: false,
  thruster_right: false,
  servo_left: false,
  servo_right: false,
});

let sweepIntervals = {};

// ------------------------------------------------------------------ //
// Helpers                                                              //
// ------------------------------------------------------------------ //

function channelGroupClass(ch) {
  return ch <= 8
    ? 'bg-primary/10 text-primary border-primary/30'
    : 'bg-warning/10 text-warning border-warning/30';
}

function colorClass(color, variant = 'text') {
  const map = {
    sky: { text: 'text-sky-400', bg: 'bg-sky-500/10', border: 'border-sky-400/30' },
    purple: { text: 'text-purple-400', bg: 'bg-purple-500/10', border: 'border-purple-400/30' },
  };
  return map[color]?.[variant] ?? '';
}

// ------------------------------------------------------------------ //
// Commands                                                             //
// ------------------------------------------------------------------ //

function sendServoCommand(channel, pwm) {
  ws.sendCommand({
    action: 'set_servo',
    channel: channel,
    pwm: pwm,
  });
}

function updatePwm(actuator, value) {
  pwmState.value[actuator.id] = Number(value);
  sendServoCommand(actuator.channel, pwmState.value[actuator.id]);
}

function centerActuator(actuator) {
  pwmState.value[actuator.id] = actuator.center;
  sendServoCommand(actuator.channel, actuator.center);
}

function centerAll() {
  actuators.value.forEach(a => centerActuator(a));
}

function stopAllTests() {
  Object.keys(sweepIntervals).forEach(id => {
    clearInterval(sweepIntervals[id]);
    delete sweepIntervals[id];
  });
  Object.keys(testingState.value).forEach(k => (testingState.value[k] = false));
}

function toggleSweepTest(actuator) {
  const id = actuator.id;

  if (testingState.value[id]) {
    // Stop
    testingState.value[id] = false;
    clearInterval(sweepIntervals[id]);
    delete sweepIntervals[id];
    centerActuator(actuator);
  } else {
    // Stop others
    stopAllTests();

    testingState.value[id] = true;
    let increasing = true;
    let current = actuator.center;

    sweepIntervals[id] = setInterval(() => {
      if (increasing) {
        current += 50;
        if (current >= actuator.max) increasing = false;
      } else {
        current -= 50;
        if (current <= actuator.min) increasing = true;
      }
      pwmState.value[id] = current;
      sendServoCommand(actuator.channel, current);
    }, 100);
  }
}

// ------------------------------------------------------------------ //
// Computed status                                                      //
// ------------------------------------------------------------------ //
const canControl = computed(() => ws.status === 'CONNECTED');

const warningMessage = computed(() => {
  if (ws.status !== 'CONNECTED') return 'WebSocket tidak terhubung ke backend.';
  if (!vessel.isConnected) return 'Pixhawk tidak terdeteksi. Pastikan ASV terhubung.';
  if (!vessel.isArmed) return 'Kapal belum ARM. Beberapa aktuator mungkin tidak merespons.';
  return null;
});
</script>

<template>
  <div class="space-y-6">

    <!-- Header Info -->
    <div class="glass-card p-5 border-l-4 border-l-primary">
      <h3 class="text-lg font-bold text-(--text-primary) flex items-center gap-2 mb-1">
        <Settings class="w-5 h-5 text-primary" />
        RC Override Testing — Aktuator
      </h3>
      <p class="text-xs text-(--text-secondary) leading-relaxed">
        Uji setiap aktuator via <b>RC Override</b> yang mensimulasikan sinyal joystick ke Pixhawk.
        Channel diambil otomatis dari konfigurasi <b>Channel Map</b>.
        Pastikan mode kapal <b class="text-warning">MANUAL</b> dan sudah <b class="text-success">ARMED</b>.
      </p>
    </div>

    <!-- Warning Banner -->
    <transition name="fade">
      <div v-if="warningMessage"
        class="flex items-start gap-3 p-4 rounded-xl border bg-warning/5 border-warning/20 text-warning">
        <AlertTriangle class="w-5 h-5 mt-0.5 shrink-0" />
        <div>
          <div class="text-xs font-bold uppercase tracking-wider mb-1">Perhatian</div>
          <p class="text-xs leading-relaxed">{{ warningMessage }}</p>
        </div>
      </div>
    </transition>

    <!-- Channel summary dari config -->
    <div class="glass-card p-4">
      <div class="flex items-center justify-between mb-3">
        <span class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest">
          Channel Aktif (dari Channel Map)
        </span>
        <router-link to="/calibration"
          class="flex items-center gap-1 text-[10px] font-bold text-primary hover:underline">
          <RefreshCw class="w-3 h-3" /> Ubah Channel Map
        </router-link>
      </div>
      <div class="grid grid-cols-4 gap-2">
        <div v-for="a in actuators" :key="a.id"
          class="flex flex-col items-center p-2 rounded-lg bg-(--bg-secondary)/50 border border-(--border-subtle)/30">
          <span class="text-[9px] font-bold text-(--text-muted) uppercase tracking-wider mb-1">{{ a.role }}</span>
          <span :class="['text-xs font-mono font-bold px-2 py-0.5 rounded border', channelGroupClass(a.channel)]">
            {{ a.label }}
          </span>
          <span class="text-[9px] text-(--text-muted) mt-1 text-center leading-tight">{{ a.name }}</span>
        </div>
      </div>
    </div>

    <!-- Aktuator Controls Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
      <div v-for="actuator in actuators" :key="actuator.id" class="glass-card p-5 flex flex-col gap-4">

        <!-- Card Header -->
        <div class="flex items-center gap-3">
          <div :class="['p-2 rounded-lg', colorClass(actuator.color, 'bg')]">
            <component :is="actuator.icon" :class="['w-4 h-4', colorClass(actuator.color, 'text')]" />
          </div>
          <div class="flex-1 min-w-0">
            <div class="text-sm font-bold text-(--text-primary)">{{ actuator.name }}</div>
            <div class="text-[10px] text-(--text-muted) truncate">{{ actuator.description }}</div>
          </div>
          <!-- Channel Badge -->
          <span :class="['text-xs font-mono font-bold px-2 py-1 rounded border shrink-0', channelGroupClass(actuator.channel)]">
            {{ actuator.label }}
          </span>
        </div>

        <!-- PWM Display -->
        <div class="flex items-center justify-between">
          <span class="text-xs text-(--text-secondary) font-mono uppercase tracking-wider">PWM</span>
          <span :class="[
            'text-lg font-black font-mono tabular-nums',
            pwmState[actuator.id] > actuator.center ? 'text-success' :
            pwmState[actuator.id] < actuator.center ? 'text-danger' : 'text-(--text-secondary)'
          ]">
            {{ pwmState[actuator.id] }} <span class="text-xs font-normal text-(--text-muted)">µs</span>
          </span>
        </div>

        <!-- Slider -->
        <div class="relative pt-1 pb-1">
          <input
            type="range"
            :min="actuator.min"
            :max="actuator.max"
            :value="pwmState[actuator.id]"
            @input="e => updatePwm(actuator, e.target.value)"
            :disabled="testingState[actuator.id] || !canControl"
            class="w-full accent-primary disabled:opacity-40 disabled:cursor-not-allowed"
          />
          <div class="flex justify-between text-[9px] text-(--text-muted) mt-1 font-mono">
            <span>{{ actuator.min }}</span>
            <span class="text-(--text-secondary)">CENTER {{ actuator.center }}</span>
            <span>{{ actuator.max }}</span>
          </div>
        </div>

        <!-- Buttons -->
        <div class="flex gap-2 mt-1">
          <button
            @click="centerActuator(actuator)"
            :disabled="testingState[actuator.id] || !canControl"
            class="flex-1 py-2 bg-(--bg-secondary) hover:bg-white/10 rounded-lg text-xs font-bold
                   text-(--text-primary) transition-colors border border-(--border-subtle)
                   disabled:opacity-40 disabled:cursor-not-allowed">
            CENTER
          </button>

          <button
            @click="toggleSweepTest(actuator)"
            :disabled="!canControl"
            :class="[
              'flex-1 py-2 flex justify-center items-center gap-2 rounded-lg text-xs font-bold transition-colors border disabled:opacity-40 disabled:cursor-not-allowed',
              testingState[actuator.id]
                ? 'bg-danger/20 text-danger border-danger/50 hover:bg-danger/30'
                : 'bg-primary/10 text-primary border-primary/30 hover:bg-primary/20'
            ]">
            <component :is="testingState[actuator.id] ? Square : Play" class="w-3 h-3" />
            {{ testingState[actuator.id] ? 'STOP TEST' : 'SWEEP TEST' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Global Controls -->
    <div class="flex gap-3">
      <button
        @click="stopAllTests"
        class="flex-1 py-3 rounded-xl font-bold text-sm border border-danger/30
               bg-danger/10 text-danger hover:bg-danger/20 transition-all">
        Stop Semua Test
      </button>
      <button
        @click="centerAll"
        :disabled="!canControl"
        class="flex-1 py-3 rounded-xl font-bold text-sm border border-(--border-subtle)
               bg-(--bg-secondary) text-(--text-primary) hover:bg-white/10 transition-all
               disabled:opacity-40 disabled:cursor-not-allowed">
        Center All (1500µs)
      </button>
    </div>

  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
