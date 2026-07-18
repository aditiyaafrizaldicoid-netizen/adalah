<script setup>
import { MapPin, Target, Save } from 'lucide-vue-next';
import { ref } from 'vue';

const latOffset = ref(0);
const lngOffset = ref(0);
</script>

<template>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
    <div class="glass-card p-6 space-y-6">
       <div class="flex items-center gap-3">
          <Target class="w-5 h-5 text-primary" />
          <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Manual Offset Correction</span>
       </div>
       
       <div class="space-y-4">
          <div class="space-y-2">
             <label class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest">Latitude Offset</label>
             <input v-model="latOffset" type="number" step="0.000001" class="w-full bg-(--bg-secondary) border border-(--border-primary) rounded-lg px-4 py-3 text-sm font-mono text-primary focus:outline-none focus:border-primary" />
          </div>
          <div class="space-y-2">
             <label class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest">Longitude Offset</label>
             <input v-model="lngOffset" type="number" step="0.000001" class="w-full bg-(--bg-secondary) border border-(--border-primary) rounded-lg px-4 py-3 text-sm font-mono text-primary focus:outline-none focus:border-primary" />
          </div>
       </div>

       <button class="btn-primary w-full py-3 flex items-center justify-center gap-2">
          <Save class="w-4 h-4" /> APPLY OFFSETS
       </button>
    </div>

    <div class="glass-card p-6 flex flex-col items-center justify-center text-center space-y-4">
       <div class="w-16 h-16 bg-primary/10 rounded-full flex items-center justify-center">
          <MapPin class="w-8 h-8 text-primary" />
       </div>
       <h4 class="text-sm font-bold text-(--text-primary) uppercase tracking-wider">Auto-Alignment Mode</h4>
       <p class="text-xs text-(--text-secondary) max-w-[200px]">Tembak koordinat pada titik referensi yang diketahui untuk kalibrasi otomatis.</p>
       <button class="bg-card hover:bg-(--bg-secondary) text-(--text-primary) px-6 py-2 rounded-lg text-[10px] font-bold uppercase transition-all">Start Auto-Align</button>
    </div>
  </div>
</template>
