<script setup>
import { Battery, Zap } from 'lucide-vue-next';

defineProps({
  percentage: { type: Number, default: 0 },
  voltage: { type: Number, default: 0 }
});
</script>

<template>
  <div class="flex items-center gap-4 bg-(--bg-secondary)/50 p-4 rounded-xl border border-(--border-primary)">
    <div class="relative">
      <Battery :class="['w-10 h-10', percentage > 20 ? 'text-success' : 'text-danger']" />
      <div 
        class="absolute inset-2 bg-current opacity-20 rounded-[1px] transition-all"
        :style="{ width: `${percentage * 0.6}%` }"
      ></div>
    </div>
    <div class="flex flex-col">
      <div class="flex items-baseline gap-2">
        <span class="text-xl font-black text-(--text-primary) font-mono">{{ percentage.toFixed(2) }}%</span>
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase">{{ voltage.toFixed(2) }}V</span>
      </div>
      <div class="flex items-center gap-1 mt-1">
        <Zap class="w-3 h-3 text-warning fill-current" />
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest">Discharging</span>
      </div>
    </div>
  </div>
</template>
