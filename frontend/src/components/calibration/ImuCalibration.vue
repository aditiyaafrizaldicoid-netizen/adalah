<script setup>
import { ref, computed, watch } from 'vue';
import { RotateCw, CheckCircle2, AlertTriangle, Wifi, WifiOff } from 'lucide-vue-next';
import { useWebsocketStore } from '@/stores/websocketStore';

const ws = useWebsocketStore();

// Step: 1=Gyro, 2=Accel Level, 3=Compass, 4=Done
const step = ref(1);
const isCalibrating = ref(false);
const progress = ref(0);
const message = ref('');
const hasError = ref(false);

const stepDefs = [
  { id: 1, label: 'Gyro', title: 'Gyroscope Calibration', calType: 'gyro',
    instruction: 'Letakkan kapal di permukaan datar dan tidak bergerak. Proses ±5 detik.' },
  { id: 2, label: 'Accel', title: 'Accelerometer Level', calType: 'accel_level',
    instruction: 'Kapal harus posisi level di air atau stand. Jangan digerakkan selama kalibrasi.' },
  { id: 3, label: 'Compass', title: 'Compass Calibration', calType: 'compass',
    instruction: 'Putar kapal perlahan 360° sambil proses berjalan. Jauhkan dari benda logam.' },
  { id: 4, label: 'Done', title: 'Calibration Complete', calType: null,
    instruction: 'Semua kalibrasi IMU berhasil diselesaikan.' },
];

const currentStep = computed(() => stepDefs.find(s => s.id === step.value) || stepDefs[0]);

// Watch imuCalibrationStatus dari websocketStore
watch(() => ws.imuCalibrationStatus, (status) => {
  if (!status) return;
  if (status.step !== step.value) return;

  progress.value = status.progress || 0;
  message.value = status.message || '';
  hasError.value = !!status.error || !!status.failed;

  if (status.success) {
    progress.value = 100;
    isCalibrating.value = false;
    // Otomatis maju ke step berikutnya setelah 1.5 detik
    setTimeout(() => {
      if (step.value < 4) step.value++;
      progress.value = 0;
      message.value = '';
      hasError.value = false;
    }, 1500);
  } else if (status.error || status.failed) {
    isCalibrating.value = false;
  }
}, { deep: true });

function startStep() {
  if (ws.status !== 'CONNECTED') return;
  const def = currentStep.value;
  if (!def.calType) return; // Step 4 = done, tidak perlu aksi

  isCalibrating.value = true;
  progress.value = 0;
  message.value = '';
  hasError.value = false;

  ws.sendCommand({
    action: 'start_imu_calibration',
    cal_type: def.calType,
    step: step.value,
  });
}

function cancelStep() {
  ws.sendCommand({ action: 'stop_imu_calibration' });
  isCalibrating.value = false;
  progress.value = 0;
  message.value = '';
  hasError.value = false;
}

function resetAll() {
  cancelStep();
  step.value = 1;
}
</script>

<template>
  <div class="space-y-8">
    <!-- Step Indicator -->
    <div class="flex justify-between items-center bg-(--bg-secondary) p-6 rounded-2xl border border-(--border-primary)">
      <div v-for="s in stepDefs" :key="s.id" class="flex flex-col items-center gap-3">
        <div :class="[
          'w-10 h-10 rounded-full flex items-center justify-center font-black transition-all duration-300',
          step > s.id  ? 'bg-success text-slate-900' :
          step === s.id ? 'bg-primary text-slate-900 ring-4 ring-primary/20' :
                         'bg-card text-(--text-secondary)'
        ]">
          <CheckCircle2 v-if="step > s.id" class="w-6 h-6" />
          <span v-else>{{ s.id }}</span>
        </div>
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase">{{ s.label }}</span>
      </div>
    </div>

    <!-- WS Disconnected Warning -->
    <div v-if="ws.status !== 'CONNECTED'"
      class="flex items-center gap-3 p-4 bg-danger/10 border border-danger/30 rounded-xl text-xs text-danger font-bold">
      <WifiOff class="w-4 h-4 flex-shrink-0" />
      ASV tidak terhubung. Sambungkan terlebih dahulu sebelum kalibrasi.
    </div>

    <!-- Main Card -->
    <div class="glass-card p-12 flex flex-col items-center justify-center text-center space-y-6">
      <!-- Spinner / Icon -->
      <div class="relative w-40 h-40">
        <RotateCw :class="[
          'w-full h-full transition-all',
          isCalibrating ? 'animate-spin text-primary' : hasError ? 'text-danger/30' : step === 4 ? 'text-success/30' : 'text-primary/20'
        ]" />
        <div class="absolute inset-0 flex items-center justify-center">
          <CheckCircle2 v-if="step === 4" class="w-16 h-16 text-success" />
          <AlertTriangle v-else-if="hasError" class="w-16 h-16 text-danger" />
          <span v-else class="text-3xl font-black text-(--text-primary) font-mono">
            {{ isCalibrating ? progress + '%' : 'READY' }}
          </span>
        </div>
      </div>

      <!-- Step Info -->
      <div class="max-w-sm space-y-2">
        <h3 class="text-lg font-bold text-(--text-primary) uppercase tracking-wider">
          {{ currentStep.title }}
        </h3>
        <p class="text-xs text-(--text-secondary)">{{ currentStep.instruction }}</p>
      </div>

      <!-- Progress Bar -->
      <div v-if="isCalibrating" class="w-full max-w-sm space-y-2">
        <div class="h-2 bg-(--bg-secondary) rounded-full overflow-hidden">
          <div class="h-full bg-primary transition-all duration-500 rounded-full"
            :style="{ width: progress + '%' }"></div>
        </div>
        <p v-if="message" class="text-[10px] text-(--text-secondary) font-mono text-left">{{ message }}</p>
      </div>

      <!-- Error Message -->
      <div v-if="hasError" class="flex items-center gap-2 text-xs text-danger font-bold">
        <AlertTriangle class="w-4 h-4" />
        {{ message || 'Kalibrasi gagal. Periksa koneksi FC dan coba lagi.' }}
      </div>

      <!-- Buttons -->
      <div v-if="step < 4" class="flex gap-3">
        <button v-if="isCalibrating" @click="cancelStep"
          class="px-8 py-3 bg-card text-(--text-primary) rounded-full text-xs font-black uppercase border border-(--border-subtle) hover:bg-danger/20 hover:text-danger hover:border-danger/30 transition-all">
          BATAL
        </button>
        <button v-else @click="startStep"
          :disabled="ws.status !== 'CONNECTED'"
          :class="[
            'px-12 py-3 rounded-full text-xs font-black uppercase transition-all',
            hasError ? 'bg-warning text-slate-900 hover:brightness-110' : 'bg-primary text-slate-900 hover:brightness-110',
            'disabled:opacity-40 disabled:cursor-not-allowed'
          ]">
          {{ hasError ? 'COBA LAGI' : 'START STEP ' + step }}
        </button>
      </div>

      <div v-else class="flex gap-3">
        <button @click="resetAll"
          class="px-8 py-3 bg-card text-(--text-primary) rounded-full text-xs font-black uppercase border border-(--border-subtle) hover:bg-(--bg-secondary) transition-all">
          ULANGI DARI AWAL
        </button>
      </div>
    </div>

    <!-- Info Box -->
    <div class="glass-card p-4 text-[10px] text-(--text-secondary) space-y-1 border-l-4 border-l-primary/50">
      <p class="font-bold text-(--text-primary) uppercase tracking-wider mb-2">Catatan Kalibrasi IMU</p>
      <p>• Gyro cal: kapal tidak boleh bergerak sama sekali selama ±5 detik</p>
      <p>• Accel cal: kapal harus posisi mendatar/level (tidak miring)</p>
      <p>• Compass cal: putar kapal 360° perlahan agar FC bisa mendeteksi medan magnet</p>
      <p>• Kalibrasi tersimpan di EEPROM Pixhawk (persisten setelah reboot)</p>
    </div>
  </div>
</template>
