<script setup>
import { ref } from 'vue';
import { RotateCw, CheckCircle2 } from 'lucide-vue-next';
import ProgressBar from '../ui/ProgressBar.vue';

const step = ref(1);
const isCalibrating = ref(false);
const progress = ref(0);

const startStep = () => {
  isCalibrating.value = true;
  progress.value = 0;
  const interval = setInterval(() => {
    progress.value += 2;
    if (progress.value >= 100) {
      clearInterval(interval);
      isCalibrating.value = false;
      if (step.value < 4) step.value++;
    }
  }, 50);
};
</script>

<template>
  <div class="space-y-8">
    <div class="flex justify-between items-center bg-(--bg-secondary) p-6 rounded-2xl border border-(--border-primary)">
      <div v-for="i in 4" :key="i" class="flex flex-col items-center gap-3">
        <div :class="[
          'w-10 h-10 rounded-full flex items-center justify-center font-black transition-all',
          step > i ? 'bg-success text-slate-900' : 
          step === i ? 'bg-primary text-slate-900 ring-4 ring-primary/20' : 'bg-card text-(--text-secondary)'
        ]">
          <CheckCircle2 v-if="step > i" class="w-6 h-6" />
          <span v-else>{{ i }}</span>
        </div>
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase">{{ i === 1 ? 'Level' : i === 2 ? 'X-Axis' : i === 3 ? 'Y-Axis' : 'Z-Axis' }}</span>
      </div>
    </div>

    <div class="glass-card p-12 flex flex-col items-center justify-center text-center space-y-6">
       <div class="relative w-48 h-48">
          <RotateCw :class="['w-full h-full text-primary/20', isCalibrating ? 'animate-spin' : '']" />
          <div class="absolute inset-0 flex items-center justify-center">
             <span class="text-4xl font-black text-(--text-primary) font-mono">{{ isCalibrating ? progress + '%' : 'READY' }}</span>
          </div>
       </div>
       
       <div class="max-w-xs">
          <h3 class="text-lg font-bold text-(--text-primary) uppercase tracking-wider">
            {{ step === 1 ? 'Level Calibration' : 'Rotate Axis ' + (step === 2 ? 'X' : step === 3 ? 'Y' : 'Z') }}
          </h3>
          <p class="text-xs text-(--text-secondary) mt-2">Posisikan kapal sesuai instruksi visual dan tekan tombol di bawah.</p>
       </div>

       <button 
         @click="startStep" 
         :disabled="isCalibrating"
         class="btn-primary px-12 py-3 rounded-full text-xs font-black"
       >
         {{ isCalibrating ? 'PROCESING...' : 'START STEP ' + step }}
       </button>
    </div>
  </div>
</template>
