<script setup>
import { Camera, Sun, Contrast, Sliders, CheckCircle2, AlertTriangle, ScanEye, Save, RefreshCw, Maximize2 } from 'lucide-vue-next';
import { ref, reactive, onMounted } from 'vue';
import { useWebsocketStore } from '@/stores/websocketStore';
import { apiUrl } from '@/config/api';
import { authHeaders } from '@/utils/session';

const ws = useWebsocketStore();

// State per kamera
const cams = reactive({
  surface: { brightness: 50, contrast: 50 },
  underwater: { brightness: 50, contrast: 70 },
});

const applyStatus = ref({}); // { surface: null | 'ok' | 'err', underwater: null | 'ok' | 'err' }

// ── Resolusi Kamera ──────────────────────────────────────────────────────
// Disimpan di DB via /api/v1/pid-config (field camera_width/camera_height),
// dibaca flightcontrolAsv1 di AWAL startup (main.py) — SEMUA threshold
// berbasis piksel di MissionEngine ikut diskalakan otomatis mengikuti resolusi
// ini (lihat MissionEngine._apply_resolution_scaling()), TIDAK perlu edit
// kode manual. BEDA dari setting lain di tab ini: TIDAK bisa berlaku live —
// kamera fisik harus di-restart untuk menerapkan resolusi baru, jadi TIDAK
// di-broadcast via WebSocket seperti min_detection_area_px2, cuma disimpan
// ke DB untuk dibaca saat proses berikutnya start.
const RESOLUTION_PRESETS = [
  { label: '1920 × 1080 (Full HD)', width: 1920, height: 1080 },
  { label: '1280 × 720 (HD)', width: 1280, height: 720 },
  { label: '640 × 360 (Low-Res)', width: 640, height: 360 },
];
const cameraWidth = ref(1920);
const cameraHeight = ref(1080);
const resolutionSaveStatus = ref(null); // null | 'ok' | 'err'

const loadResolutionSettings = async () => {
  try {
    const res = await fetch(apiUrl('/api/v1/pid-config'));
    if (res.ok) {
      const result = await res.json();
      if (result.data) {
        if (result.data.camera_width) cameraWidth.value = result.data.camera_width;
        if (result.data.camera_height) cameraHeight.value = result.data.camera_height;
      }
    }
  } catch (err) {
    console.error('Failed to load camera resolution from DB:', err);
  }
};

const applyResolutionSettings = async () => {
  try {
    const res = await fetch(apiUrl('/api/v1/pid-config'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ camera_width: cameraWidth.value, camera_height: cameraHeight.value }),
    });
    // fetch() only rejects on network failure -- an HTTP error status (4xx/5xx)
    // still resolves normally, so res.ok must be checked explicitly or a failed
    // save would silently report success.
    resolutionSaveStatus.value = res.ok ? 'ok' : 'err';
  } catch (err) {
    console.error('Failed to persist camera resolution in database:', err);
    resolutionSaveStatus.value = 'err';
  }
  setTimeout(() => { resolutionSaveStatus.value = null; }, 3000);
};

const applyResolutionPreset = (preset) => {
  cameraWidth.value = preset.width;
  cameraHeight.value = preset.height;
  applyResolutionSettings();
};

const resetResolutionSettings = () => {
  cameraWidth.value = 1920;
  cameraHeight.value = 1080;
  applyResolutionSettings();
};

// ── Deteksi Object: Minimum Area (px²) ──────────────────────────────────
// Global untuk pipeline deteksi YOLO (bukan per-kamera) — deteksi bola dengan
// area bounding box di bawah nilai ini diabaikan sepenuhnya di sumbernya
// (vision/tracker.py), sebelum sampai ke mission logic apa pun. Disimpan di
// DB via /api/v1/pid-config (field min_detection_area_px2), sama seperti
// AI PID Tuning — dibaca flightcontrolAsv1 saat startup & live via WS.
const minDetectionAreaPx2 = ref(4000);
const detectionSaveStatus = ref(null); // null | 'ok' | 'err'

const loadDetectionSettings = async () => {
  try {
    const res = await fetch(apiUrl('/api/v1/pid-config'));
    if (res.ok) {
      const result = await res.json();
      if (result.data && result.data.min_detection_area_px2 !== undefined) {
        minDetectionAreaPx2.value = result.data.min_detection_area_px2;
      }
    }
  } catch (err) {
    console.error('Failed to load detection settings from DB:', err);
  }
};

const applyDetectionSettings = async () => {
  // 1. Broadcast live via WebSocket ke ASV yang sedang terhubung
  ws.updatePid({ min_detection_area_px2: minDetectionAreaPx2.value });

  // 2. Persist di Database via HTTP REST API
  try {
    const res = await fetch(apiUrl('/api/v1/pid-config'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ min_detection_area_px2: minDetectionAreaPx2.value }),
    });
    // fetch() only rejects on network failure -- an HTTP error status (4xx/5xx)
    // still resolves normally, so res.ok must be checked explicitly or a failed
    // save would silently report success.
    detectionSaveStatus.value = res.ok ? 'ok' : 'err';
  } catch (err) {
    console.error('Failed to persist detection settings in database:', err);
    detectionSaveStatus.value = 'err';
  }
  setTimeout(() => { detectionSaveStatus.value = null; }, 3000);
};

const resetDetectionSettings = () => {
  minDetectionAreaPx2.value = 4000;
  applyDetectionSettings();
};

onMounted(() => {
  loadDetectionSettings();
  loadResolutionSettings();
});

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
  <div class="space-y-6">
    <!-- Camera Resolution (global, saved to DB, requires flightcontrolAsv1 restart) -->
    <div class="glass-card p-6 space-y-4">
      <div class="flex justify-between items-center border-b border-(--border-subtle) pb-4">
        <div class="flex items-center gap-3">
          <Maximize2 class="w-5 h-5 text-primary" />
          <div>
            <h2 class="text-sm font-black text-(--text-primary) uppercase tracking-widest">Camera Resolution</h2>
            <p class="text-[10px] text-(--text-secondary) font-bold uppercase">Semua threshold piksel tracking otomatis menyesuaikan</p>
          </div>
        </div>
        <button @click="resetResolutionSettings" class="text-[10px] font-bold text-(--text-secondary) hover:text-(--text-primary) uppercase flex items-center gap-1">
          <RefreshCw class="w-3 h-3" /> Reset Default
        </button>
      </div>

      <div class="grid grid-cols-3 gap-2 max-w-lg">
        <button v-for="preset in RESOLUTION_PRESETS" :key="preset.label" @click="applyResolutionPreset(preset)"
          :class="['py-3 px-2 rounded-xl text-[10px] font-bold uppercase tracking-wide transition-all border',
            cameraWidth === preset.width && cameraHeight === preset.height
              ? 'bg-primary text-slate-900 border-primary shadow-lg shadow-primary/20'
              : 'bg-(--bg-secondary) text-(--text-secondary) border-(--border-subtle) hover:text-(--text-primary)']">
          {{ preset.label }}
        </button>
      </div>

      <div class="flex items-end gap-3 bg-(--bg-secondary) p-4 rounded-xl border border-(--border-primary) max-w-lg">
        <div class="flex-1 space-y-1">
          <span class="text-[10px] font-black uppercase text-(--text-secondary)">Width (px)</span>
          <input type="number" step="1" min="1" v-model.number="cameraWidth"
            class="w-full bg-card border border-(--border-subtle) rounded px-2 py-1.5 text-xs font-mono text-(--text-primary)" />
        </div>
        <span class="text-(--text-muted) pb-1.5 font-bold">×</span>
        <div class="flex-1 space-y-1">
          <span class="text-[10px] font-black uppercase text-(--text-secondary)">Height (px)</span>
          <input type="number" step="1" min="1" v-model.number="cameraHeight"
            class="w-full bg-card border border-(--border-subtle) rounded px-2 py-1.5 text-xs font-mono text-(--text-primary)" />
        </div>
      </div>

      <p class="text-[10px] text-(--text-muted) font-bold uppercase max-w-lg">
        ⚠ Butuh restart proses flightcontrolAsv1 (main.py) di boat untuk berlaku — kamera fisik tidak bisa diganti resolusinya secara live.
      </p>

      <div class="flex items-center justify-between pt-2">
        <transition name="fade">
          <div v-if="resolutionSaveStatus" :class="['text-xs font-bold flex items-center gap-2',
            resolutionSaveStatus === 'ok' ? 'text-success' : 'text-danger']">
            <CheckCircle2 v-if="resolutionSaveStatus === 'ok'" class="w-4 h-4" />
            <AlertTriangle v-else class="w-4 h-4" />
            {{ resolutionSaveStatus === 'ok' ? 'Saved to DB (restart to apply)' : 'Gagal menyimpan ke database' }}
          </div>
        </transition>
        <button @click="applyResolutionSettings"
          class="bg-primary hover:bg-red-600 text-slate-900 font-black px-6 py-3 rounded-xl text-xs uppercase tracking-widest flex items-center gap-2 transition-all shadow-lg shadow-primary/20 ml-auto">
          <Save class="w-4 h-4" /> Save
        </button>
      </div>
    </div>

    <!-- Object Detection Noise Floor (global, saved to DB) -->
    <div class="glass-card p-6 space-y-4">
      <div class="flex justify-between items-center border-b border-(--border-subtle) pb-4">
        <div class="flex items-center gap-3">
          <ScanEye class="w-5 h-5 text-primary" />
          <div>
            <h2 class="text-sm font-black text-(--text-primary) uppercase tracking-widest">Object Detection Noise Floor</h2>
            <p class="text-[10px] text-(--text-secondary) font-bold uppercase">Abaikan deteksi bola YOLO yang lebih kecil dari ini</p>
          </div>
        </div>
        <button @click="resetDetectionSettings" class="text-[10px] font-bold text-(--text-secondary) hover:text-(--text-primary) uppercase flex items-center gap-1">
          <RefreshCw class="w-3 h-3" /> Reset Default
        </button>
      </div>

      <div class="space-y-3 bg-(--bg-secondary) p-4 rounded-xl border border-(--border-primary) max-w-md">
        <div class="flex justify-between items-center text-[10px] font-black uppercase">
          <span class="text-(--text-secondary)">Ignore Detections Below (px²)</span>
          <span class="font-mono text-sm text-primary">{{ minDetectionAreaPx2 }} px²</span>
        </div>
        <input type="range" min="1" max="20000" step="10" v-model.number="minDetectionAreaPx2"
          class="w-full accent-primary cursor-pointer" />
        <input type="number" step="1" v-model.number="minDetectionAreaPx2"
          class="w-full bg-card border border-(--border-subtle) rounded px-2 py-1 text-xs font-mono text-(--text-primary)" />
      </div>

      <div class="flex items-center justify-between pt-2">
        <transition name="fade">
          <div v-if="detectionSaveStatus" :class="['text-xs font-bold flex items-center gap-2',
            detectionSaveStatus === 'ok' ? 'text-success' : 'text-danger']">
            <CheckCircle2 v-if="detectionSaveStatus === 'ok'" class="w-4 h-4" />
            <AlertTriangle v-else class="w-4 h-4" />
            {{ detectionSaveStatus === 'ok' ? 'Applied & Saved to DB' : 'Gagal menyimpan ke database' }}
          </div>
        </transition>
        <button @click="applyDetectionSettings"
          class="bg-primary hover:bg-red-600 text-slate-900 font-black px-6 py-3 rounded-xl text-xs uppercase tracking-widest flex items-center gap-2 transition-all shadow-lg shadow-primary/20 ml-auto">
          <Save class="w-4 h-4" /> Apply & Save
        </button>
      </div>
    </div>

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
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
