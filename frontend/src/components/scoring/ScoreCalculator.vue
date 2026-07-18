<script setup>
import { useScoringStore } from '@/stores/scoringStore';
import { Info } from 'lucide-vue-next';

const scoring = useScoringStore();
</script>

<template>
  <div class="glass-card p-6 border-t-4 border-t-primary">
    <div class="flex items-center gap-2 mb-6">
       <Info class="w-5 h-5 text-primary" />
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Score Formula Calculator</span>
    </div>

    <div class="space-y-6">
       <div class="p-6 bg-background rounded-2xl border border-(--border-primary) text-center">
          <span class="text-[10px] text-(--text-secondary) font-black uppercase tracking-[0.2em] block mb-2">Calculated Total</span>
          <span class="text-5xl font-black text-primary font-mono tracking-tighter">{{ scoring.totalScore.toFixed(2) }}</span>
       </div>

       <div class="grid grid-cols-2 gap-4">
          <div class="p-4 bg-card/30 rounded-xl border border-(--border-subtle)">
             <span class="text-[10px] text-(--text-secondary) font-bold uppercase block mb-1">NM Score</span>
             <span class="text-lg font-black text-(--text-primary) font-mono">{{ scoring.nm === 20 ? '100.0' : (10 * (2*scoring.nm - scoring.p) / 900).toFixed(1) }}</span>
          </div>
          <div class="p-4 bg-card/30 rounded-xl border border-(--border-subtle)">
             <span class="text-[10px] text-(--text-secondary) font-bold uppercase block mb-1">IM + DC Bonus</span>
             <span class="text-lg font-black text-success font-mono">+{{ scoring.imh + scoring.imb + scoring.dc }}</span>
          </div>
       </div>
    </div>
  </div>
</template>
