<script setup>
import { Camera, Sun, Contrast, Sliders, CheckCircle2, AlertTriangle } from 'lucide-vue-next';
import { ref, reactive } from 'vue';
import { useWebsocketStore } from '@/stores/websocketStore';

const ws = useWebsocketStore();

// State per kamera
const cams = reactive({
  surface: { brightness: 50, contrast: 50 },
  underwater: { brightness: 50, contrast: 70 },
});

const applyStatus = ref({}); // { surface: null | 'ok' | 'err', underwater: null | 'ok' | 'err' }

function applySettings(camKey) {
  if (ws.status !== 'CONNECTED') {
    applyStatus.value[camKey] = 'err';
    setTimeout(() => { delete applyStatus.value[camKey]; }, 3000);
    return;
  }
  ws.sendCommand({
    action: 'set_camera_params',
    camera: camKey,
    brightness: cams[camKey].brightness,
    contrast: cams[camKey].contrast,
  });
  applyStatus.value[camKey] = 'ok';
  setTimeout(() => { delete applyStatus.value[camKey]; }, 3000);
}

function resetCam(camKey) {
  const defaults = { surface: { brightness: 50, contrast: 50 }, underwater: { brightness: 50, contrast: 70 } };
  cams[camKey].brightness = defaults[camKey].brightness;
  cams[camKey].contrast = defaults[camKey].contrast;
}
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <div v-for="(cam, key) in cams" :key="key" class="glass-card p-6 space-y-6">
      <div class="flex items-center gap-3">
        <Camera class="w-5 h-5 text-primary" />
        <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">
          {{ key === 'surface' ? 'Surface' : 'Underwater' }} Calibration
        </span>
      </div>

      <!-- Live Preview Placeholder -->
      <div class="aspect-video bg-(--bg-secondary) rounded-lg flex items-center justify-center border border-(--border-primary)">
        <span class="text-[10px] text-(--text-muted) font-black uppercase tracking-widest">Live Preview (via Camera Feed)</span>
      </div>

      <div class="space-y-6">
        <div class="space-y-3">
          <div class="flex justify-between">
            <span class="text-[10px] font-bold text-(--text-secondary) uppercase flex items-center gap-2">
              <Sun class="w-3 h-3" /> Brightness
            </span>
            <span class="text-[10px] font-mono text-primary">{{ cam.brightness }}%</span>
          </div>
          <input v-model.number="cam.brightness" type="range" min="0" max="100"
            class="w-full accent-primary bg-card h-1.5 rounded-full appearance-none cursor-pointer" />
        </div>

        <div class="space-y-3">
          <div class="flex justify-between">
            <span class="text-[10px] font-bold text-(--text-secondary) uppercase flex items-center gap-2">
              <Contrast class="w-3 h-3" /> Contrast
            </span>
            <span class="text-[10px] font-mono text-primary">{{ cam.contrast }}%</span>
          </div>
          <input v-model.number="cam.contrast" type="range" min="0" max="100"
            class="w-full accent-primary bg-card h-1.5 rounded-full appearance-none cursor-pointer" />
        </div>
      </div>

      <!-- Status feedback -->
      <transition name="fade">
        <div v-if="applyStatus[key]" :class="['p-3 rounded-xl text-[10px] font-bold flex items-center gap-2',
          applyStatus[key] === 'ok' ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger']">
          <CheckCircle2 v-if="applyStatus[key] === 'ok'" class="w-3.5 h-3.5" />
          <AlertTriangle v-else class="w-3.5 h-3.5" />
          {{ applyStatus[key] === 'ok' ? 'Parameter dikirim ke ASV' : 'Gagal: ASV tidak terhubung' }}
        </div>
      </transition>

      <div class="flex gap-2">
        <button @click="resetCam(key)"
          class="flex-1 py-2 bg-card hover:bg-(--bg-secondary) rounded-lg text-[10px] font-bold uppercase transition-all">
          Reset Defaults
        </button>
        <button @click="applySettings(key)" :disabled="ws.status !== 'CONNECTED'"
          class="flex-1 py-2 bg-primary text-slate-900 rounded-lg text-[10px] font-black uppercase transition-all disabled:opacity-40">
          Apply Settings
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
