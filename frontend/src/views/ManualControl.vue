<script setup>
import { computed, watch, ref, reactive, onMounted, onUnmounted } from 'vue';
import { Gamepad2, Keyboard, AlertTriangle, Zap, ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Radio } from 'lucide-vue-next';
import { useGamepad } from '@/composables/useGamepad';
import { useWebsocketStore } from '@/stores/websocketStore';
import { useVesselStore } from '@/stores/vesselStore';
import ArmingControl from '@/components/monitoring/ArmingControl.vue';

const { isConnected: isGamepadConnected, axes, buttons, gamepadName, error } = useGamepad();
const wsStore = useWebsocketStore();
const vessel = useVesselStore();

// UI State
const updateRateHz = ref(10); // How many times per second to send commands
let sendInterval = null;

// ── Sumber kendali manual: Mini PC vs Remote RC fisik ───────────────────────
// Saat 'remote', Mini PC memblokir SEMUA perintah geraknya sendiri (termasuk netral
// yang dikirim tiap frame saat idle) dan melepaskan RC override, sehingga stik remote
// benar-benar memegang kemudi. Halaman ini ikut berhenti mengirim supaya tidak
// mengganggu — meski kapal juga sudah menolaknya di sisi sana.
const isRemoteControl = computed(() => vessel.manualSource === 'remote');

// Tombol PEMILIHNYA ada di Dashboard (ControlSourceControl.vue) — halaman ini cuma
// perlu tahu siapa yang sedang memegang kemudi, supaya berhenti mengirim perintah
// dan memberi tahu operator kenapa joysticknya mendadak diam.

// Keyboard State
const keys = reactive({
  w: false,
  a: false,
  s: false,
  d: false
});

const handleKeyDown = (e) => {
  const k = e.key.toLowerCase();
  if (keys.hasOwnProperty(k)) keys[k] = true;
};

const handleKeyUp = (e) => {
  const k = e.key.toLowerCase();
  if (keys.hasOwnProperty(k)) keys[k] = false;
};

// Deadzone for analog sticks (0.0 to 1.0)
const deadzone = 0.1;

// Math helper
const applyDeadzone = (val) => Math.abs(val) < deadzone ? 0 : val;
const mapPwm = (val) => Math.round(800 + (val * 500)); // Map -1..1 to 1000..2000
const mapPwmStering = (val) => Math.round(1500 + (val * 500)); // Map -1..1 to 1000..2000

// We assume Standard Gamepad layout:
// axes[0] = Left Stick X (Steering)
// axes[1] = Left Stick Y (Throttle - Up is negative usually)

const throttle = computed(() => {
  let gpThrottle = 0;
  if (isGamepadConnected.value && axes.value.length >= 2) {
    gpThrottle = -applyDeadzone(axes.value[1]);
  }

  let kbThrottle = 0;
  if (keys.w && !keys.s) kbThrottle = 0.8; // Max 80% if using keyboard for safety
  if (keys.s && !keys.w) kbThrottle = -0.8;

  // Ambil input yang nilainya lebih besar (Keyboard vs Joystick)
  return Math.abs(gpThrottle) > Math.abs(kbThrottle) ? gpThrottle : kbThrottle;
});

const steering = computed(() => {
  let gpSteer = 0;
  if (isGamepadConnected.value && axes.value.length >= 2) {
    gpSteer = applyDeadzone(axes.value[2]);
  }

  let kbSteer = 0;
  if (keys.d && !keys.a) kbSteer = 1.0;
  if (keys.a && !keys.d) kbSteer = -1.0;

  return Math.abs(gpSteer) > Math.abs(kbSteer) ? gpSteer : kbSteer;
});

// Calculate Vectored Mix
const vectoredCmd = computed(() => {
  let t = throttle.value;
  let s = steering.value;

  // Calculate PWM for Left and Right Throttle (Differential Thrust)
  // When steering right (s > 0), left motor speeds up, right motor slows down
  let tl = t + (s * 0.5);
  let tr = t - (s * 0.5);

  // Clamp values between -1 and 1
  tl = Math.max(-1, Math.min(1, tl));
  tr = Math.max(-1, Math.min(1, tr));

  // Calculate PWM for Servo (Vectored steering)
  // Both servos turn to the right (positive) or left (negative)
  let sl = s;
  let sr = s;

  return {
    throttle_left: mapPwm(tl),
    throttle_right: mapPwm(tr),
    servo_left: mapPwmStering(sl),
    servo_right: mapPwmStering(sr)
  };
});

const sendDriveCommand = () => {
  if (isRemoteControl.value) return;   // kemudi dipegang remote RC — jangan diganggu
  const isUsingKeyboard = keys.w || keys.a || keys.s || keys.d;
  if ((isGamepadConnected.value || isUsingKeyboard) && vessel.isArmed) {
    wsStore.sendCommand({
      action: "manual_control",
      x: Math.round(throttle.value * 1000),
      y: Math.round(steering.value * 1000),
      r: Math.round(steering.value * 1000),
      z: 500,
    });
  }
};


onMounted(() => {
  // Sinkronkan tampilan dengan sumber kendali yang benar-benar aktif di kapal —
  // halaman bisa saja dibuka setelah kendali dipindah dari sesi/tab lain.
  wsStore.requestManualSource();
  // Start the control loop
  sendInterval = setInterval(sendDriveCommand, 1000 / updateRateHz.value);
  window.addEventListener('keydown', handleKeyDown);
  window.addEventListener('keyup', handleKeyUp);
});

onUnmounted(() => {
  if (sendInterval) clearInterval(sendInterval);
  window.removeEventListener('keydown', handleKeyDown);
  window.removeEventListener('keyup', handleKeyUp);
});

</script>

<template>
  <div class="h-full flex flex-col p-3 sm:p-6 space-y-4 sm:space-y-6 overflow-y-auto">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-bold tracking-tight text-white flex items-center gap-3">
          <Gamepad2 class="w-7 h-7 text-(--accent-primary)" />
          Manual Control (Joystick & Keyboard)
        </h1>
        <p class="text-(--text-secondary) mt-1">Kendalikan pergerakan ASV menggunakan Gamepad atau tombol keyboard
          <b>WASD</b>.</p>
      </div>
    </div>

    <!-- Status Alerts -->
    <div v-if="error" class="p-4 bg-danger/10 border border-danger/30 rounded-xl text-danger flex items-center gap-3">
      <AlertTriangle class="w-5 h-5" />
      {{ error }}
    </div>

    <div v-if="isRemoteControl"
      class="p-4 bg-warning/10 border border-warning/30 rounded-xl text-warning flex items-center gap-3">
      <Radio class="w-5 h-5 shrink-0" />
      <span>
        <b>Kemudi dipegang REMOTE RC fisik.</b> Joystick, keyboard, dan misi otomatis
        dinonaktifkan sampai kendali dikembalikan ke Mini PC lewat panel
        <b>Sumber Kendali</b> di halaman Dashboard.
      </span>
    </div>

    <!-- Content Grid -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

      <!-- Left Column: Joystick Status -->
      <div class="lg:col-span-2 space-y-6">

        <!-- Gamepad Connection Panel -->
        <div class="bg-(--bg-card) border border-(--border-primary) rounded-xl p-6 shadow-xl relative overflow-hidden">
          <div class="absolute top-0 right-0 p-3 opacity-10">
            <Gamepad2 class="w-32 h-32" />
          </div>

          <div class="flex items-center gap-4 mb-6 relative z-10">
            <div :class="[
              'w-12 h-12 rounded-full flex items-center justify-center shadow-lg transition-colors',
              isGamepadConnected ? 'bg-success/20 text-success' : 'bg-info/20 text-info'
            ]">
              <Gamepad2 v-if="isGamepadConnected" class="w-6 h-6" />
              <Keyboard v-else class="w-6 h-6" />
            </div>
            <div>
              <h2 class="text-lg font-bold text-(--text-primary)">
                {{ isGamepadConnected ? 'Gamepad Terhubung' : 'Gunakan Keyboard (WASD)' }}
              </h2>
              <p class="text-sm text-(--text-secondary)">
                {{ isGamepadConnected ? gamepadName : 'Colokkan joystick atau gunakan tombol W, A, S, D di keyboard.' }}
              </p>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-4 relative z-10">
            <div class="bg-(--bg-secondary) rounded-lg p-4 border border-(--border-subtle)">
              <div class="text-xs text-(--text-secondary) mb-1 font-semibold uppercase tracking-wider">Throttle
                (Maju/Mundur)</div>
              <div class="flex items-end gap-2">
                <span class="text-3xl font-bold font-mono" :class="throttle >= 0 ? 'text-success' : 'text-warning'">
                  {{ (throttle * 100).toFixed(0) }}%
                </span>
              </div>
              <!-- Visual Indicator -->
              <div class="w-full h-2 bg-slate-800 rounded-full mt-3 flex items-center justify-center relative">
                <div class="absolute h-full bg-success rounded-full"
                  :style="{ width: throttle > 0 ? (throttle * 50) + '%' : '0%', left: '50%' }"></div>
                <div class="absolute h-full bg-warning rounded-full"
                  :style="{ width: throttle < 0 ? (-throttle * 50) + '%' : '0%', right: '50%' }"></div>
                <div class="w-1 h-3 bg-white absolute z-10"></div>
              </div>
            </div>

            <div class="bg-(--bg-secondary) rounded-lg p-4 border border-(--border-subtle)">
              <div class="text-xs text-(--text-secondary) mb-1 font-semibold uppercase tracking-wider">Steering (Belok)
              </div>
              <div class="flex items-end gap-2">
                <span class="text-3xl font-bold font-mono" :class="steering >= 0 ? 'text-info' : 'text-info'">
                  {{ (steering * 100).toFixed(0) }}%
                </span>
              </div>
              <!-- Visual Indicator -->
              <div class="w-full h-2 bg-slate-800 rounded-full mt-3 flex items-center justify-center relative">
                <div class="absolute h-full bg-info rounded-full"
                  :style="{ width: steering > 0 ? (steering * 50) + '%' : '0%', left: '50%' }"></div>
                <div class="absolute h-full bg-info rounded-full"
                  :style="{ width: steering < 0 ? (-steering * 50) + '%' : '0%', right: '50%' }"></div>
                <div class="w-1 h-3 bg-white absolute z-10"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Vectored Output Monitor -->
        <div class="bg-(--bg-card) border border-(--border-primary) rounded-xl p-6 shadow-xl">
          <h3 class="font-bold text-(--text-primary) mb-4 flex items-center gap-2">
            <Zap class="w-4 h-4 text-warning" /> Live PWM Output (Vectored)
          </h3>

          <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div v-for="(pwm, name) in vectoredCmd" :key="name"
              class="bg-(--bg-secondary) border border-(--border-subtle) rounded-lg p-3 text-center">
              <div class="text-[10px] text-(--text-secondary) uppercase font-bold tracking-widest mb-1">
                {{ name.replace('_', ' ') }}
              </div>
              <div class="font-mono text-xl font-bold text-white">
                {{ pwm }}<span class="text-xs text-slate-500 font-normal">µs</span>
              </div>
            </div>
          </div>

          <div class="mt-4 text-xs text-warning p-3 rounded-lg border border-warning/20">
            <strong>Catatan:</strong> Output di atas akan dikirimkan sebanyak <b>{{ updateRateHz }} kali per detik</b>
            ke Pixhawk hanya jika ASV dalam keadaan <strong>ARMED</strong>.
          </div>
        </div>
      </div>

      <!-- Right Column: Arming Control -->
      <div class="space-y-6">
                <ArmingControl />
      </div>

    </div>
  </div>
</template>
