<script setup>
import { Camera, Sun, Contrast, Sliders } from 'lucide-vue-next';
import { ref } from 'vue';

const brightness = ref(50);
const contrast = ref(50);
</script>

<template>
  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <div v-for="cam in ['Surface', 'Underwater']" :key="cam" class="glass-card p-6 space-y-6">
       <div class="flex items-center gap-3">
          <Camera class="w-5 h-5 text-primary" />
          <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">{{ cam }} Calibration</span>
       </div>

       <div class="aspect-video bg-(--bg-secondary) rounded-lg flex items-center justify-center border border-(--border-primary)">
          <span class="text-[10px] text-(--text-muted) font-black uppercase tracking-widest">Live Preview</span>
       </div>

       <div class="space-y-6">
          <div class="space-y-3">
             <div class="flex justify-between">
                <span class="text-[10px] font-bold text-(--text-secondary) uppercase flex items-center gap-2"><Sun class="w-3 h-3" /> Brightness</span>
                <span class="text-[10px] font-mono text-primary">{{ brightness }}%</span>
             </div>
             <input v-model="brightness" type="range" class="w-full accent-primary bg-card h-1.5 rounded-full appearance-none cursor-pointer" />
          </div>

          <div class="space-y-3">
             <div class="flex justify-between">
                <span class="text-[10px] font-bold text-(--text-secondary) uppercase flex items-center gap-2"><Contrast class="w-3 h-3" /> Contrast</span>
                <span class="text-[10px] font-mono text-primary">{{ contrast }}%</span>
             </div>
             <input v-model="contrast" type="range" class="w-full accent-primary bg-card h-1.5 rounded-full appearance-none cursor-pointer" />
          </div>
       </div>

       <div class="flex gap-2">
          <button class="flex-1 py-2 bg-card hover:bg-(--bg-secondary) rounded-lg text-[10px] font-bold uppercase transition-all">Reset Defaults</button>
          <button class="flex-1 py-2 bg-primary text-slate-900 rounded-lg text-[10px] font-black uppercase transition-all">Apply Settings</button>
       </div>
    </div>
  </div>
</template>
