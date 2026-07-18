<script setup>
import { useScoringStore } from '@/stores/scoringStore';
import { Flag, Timer, AlertCircle } from 'lucide-vue-next';

const scoring = useScoringStore();
</script>

<template>
  <div class="glass-card overflow-hidden">
    <div class="p-4 bg-card/30 border-b border-(--border-subtle) flex justify-between items-center">
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Mission Score Breakdown</span>
    </div>
    <div class="p-6 grid grid-cols-3 gap-6">
       <div class="space-y-1">
          <div class="flex items-center gap-2 text-primary">
             <Flag class="w-4 h-4" />
             <span class="text-[10px] font-black uppercase tracking-widest">NM (Progress)</span>
          </div>
          <span class="text-2xl font-black text-(--text-primary) font-mono">{{ scoring.nm }}</span>
          <p class="text-[8px] text-(--text-secondary) font-bold uppercase">Max 20.0</p>
       </div>

       <div class="space-y-1">
          <div class="flex items-center gap-2 text-warning">
             <Timer class="w-4 h-4" />
             <span class="text-[10px] font-black uppercase tracking-widest">NT (Time)</span>
          </div>
          <span class="text-2xl font-black text-(--text-primary) font-mono">{{ scoring.nt }}s</span>
          <p class="text-[8px] text-(--text-secondary) font-bold uppercase">Seconds elapsed</p>
       </div>

       <div class="space-y-1">
          <div class="flex items-center gap-2 text-danger">
             <AlertCircle class="w-4 h-4" />
             <span class="text-[10px] font-black uppercase tracking-widest">P (Penalty)</span>
          </div>
          <span class="text-2xl font-black text-(--text-primary) font-mono">{{ scoring.p }}</span>
          <p class="text-[8px] text-(--text-secondary) font-bold uppercase">-5 per penalty</p>
       </div>
    </div>
  </div>
</template>
