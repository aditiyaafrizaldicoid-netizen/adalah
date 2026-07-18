<script setup>
import { Save, FolderOpen, Play } from 'lucide-vue-next';

const presets = [
  { name: 'Standard Qualifying', steps: 7, date: '2026-05-01' },
  { name: 'Fast Run (Aggressive)', steps: 5, date: '2026-05-05' },
  { name: 'Safety Mode (Low Speed)', steps: 7, date: '2026-05-10' },
];
</script>

<template>
  <div class="glass-card p-5 space-y-4">
    <div class="flex items-center gap-2 mb-2">
      <FolderOpen class="w-4 h-4 text-primary" />
      <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Mission Presets</span>
    </div>
    
    <div class="space-y-2">
      <button v-for="p in presets" :key="p.name" class="w-full flex items-center justify-between p-3 bg-card/50 rounded-xl border border-(--border-subtle) hover:border-primary/50 transition-all group">
         <div class="text-left">
           <span class="text-xs font-bold text-(--text-primary) block group-hover:text-primary transition-colors">{{ p.name }}</span>
           <span class="text-[10px] text-(--text-secondary) uppercase font-bold">{{ p.steps }} Steps | {{ p.date }}</span>
         </div>
         <Play class="w-3 h-3 text-(--text-muted) group-hover:text-primary fill-current" />
      </button>
    </div>
    
    <button class="w-full py-2.5 border-2 border-dashed border-(--border-subtle) rounded-xl text-[10px] font-black text-(--text-muted) uppercase hover:border-slate-500 hover:text-(--text-secondary) transition-all flex items-center justify-center gap-2">
       <Save class="w-3.5 h-3.5" /> Save Current as Preset
    </button>
  </div>
</template>
