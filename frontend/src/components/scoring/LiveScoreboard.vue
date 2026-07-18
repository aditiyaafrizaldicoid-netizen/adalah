<script setup>
import { Trophy } from 'lucide-vue-next';

const teams = [
  { name: 'TEAM KKI-01 (YOU)', score: 145.2, rank: 1, trend: 'up' },
  { name: 'TEAM ASV-ROBOTIC', score: 138.5, rank: 2, trend: 'down' },
  { name: 'TIM MARITIM-UNIV', score: 122.1, rank: 3, trend: 'stable' },
];
</script>

<template>
  <div class="glass-card overflow-hidden">
    <div class="p-4 bg-card/30 border-b border-(--border-subtle) flex justify-between items-center">
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest flex items-center gap-2">
         <Trophy class="w-4 h-4 text-warning" /> Competition Live Leaderboard
       </span>
    </div>
    <div class="divide-y divide-slate-800/50">
       <div v-for="team in teams" :key="team.name" class="p-4 flex justify-between items-center hover:bg-card/30 transition-all">
          <div class="flex items-center gap-4">
             <span :class="['w-6 h-6 rounded flex items-center justify-center font-black text-[10px]', team.rank === 1 ? 'bg-warning text-slate-900' : 'bg-card text-(--text-secondary)']">
               {{ team.rank }}
             </span>
             <span class="text-[10px] font-bold text-(--text-primary) uppercase tracking-wider">{{ team.name }}</span>
          </div>
          <span class="text-xs font-black text-primary font-mono">{{ team.score.toFixed(1) }}</span>
       </div>
    </div>
  </div>
</template>
