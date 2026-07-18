<script setup>
import { Camera, Check, X } from 'lucide-vue-next';
import { useScoringStore } from '@/stores/scoringStore';

const scoring = useScoringStore();
const ratings = [0, 1, 3, 5];
</script>

<template>
  <div class="glass-card p-6 space-y-6">
    <div class="flex items-center gap-3">
       <Camera class="w-5 h-5 text-primary" />
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Image Quality Judge</span>
    </div>

    <div class="grid grid-cols-2 gap-4">
       <div v-for="type in ['imh', 'imb']" :key="type" class="space-y-3">
          <span class="text-[10px] font-bold text-(--text-secondary) uppercase block tracking-widest">{{ type === 'imh' ? 'Surface' : 'Underwater' }}</span>
          <div class="aspect-square bg-(--bg-secondary) rounded-xl border border-(--border-primary) flex items-center justify-center relative overflow-hidden group">
             <span class="text-[10px] text-(--text-muted) font-black uppercase">Captured Image</span>
             <div class="absolute inset-0 bg-primary/10 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                <button class="bg-primary text-slate-900 px-3 py-1.5 rounded-lg font-black text-[10px] uppercase">Analyze</button>
             </div>
          </div>
          <div class="flex gap-1">
             <button 
               v-for="r in ratings" 
               :key="r"
               @click="type === 'imh' ? scoring.setImh(r) : scoring.setImb(r)"
               :class="[
                 'flex-1 py-2 rounded-lg font-black text-xs transition-all border',
                 (type === 'imh' ? scoring.imh : scoring.imb) === r ? 'bg-primary text-slate-900 border-primary shadow-lg shadow-primary/20' : 'bg-card text-(--text-secondary) border-(--border-subtle)'
               ]"
             >
               {{ r }}
             </button>
          </div>
       </div>
    </div>
  </div>
</template>
