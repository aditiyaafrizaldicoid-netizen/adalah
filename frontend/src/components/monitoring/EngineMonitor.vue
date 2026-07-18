<script setup>
import { Activity, Zap } from 'lucide-vue-next';

defineProps({
  thrusterL: { type: Number, default: 0 },
  thrusterR: { type: Number, default: 0 },
  rpmL: { type: Number, default: 0 },
  rpmR: { type: Number, default: 0 }
});
</script>

<template>
  <div class="glass-card p-5 space-y-6">
    <div class="flex items-center gap-3">
       <Zap class="w-5 h-5 text-warning" />
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Engine Load Monitor</span>
    </div>

    <div class="space-y-6">
      <div v-for="side in ['Left', 'Right']" :key="side" class="space-y-2">
        <div class="flex justify-between items-end">
          <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest">{{ side }} Thruster</span>
          <span class="text-xs font-mono font-black text-(--text-primary)">{{ (side === 'Left' ? rpmL : rpmR).toFixed(0) }} <span class="text-[8px] text-(--text-secondary)">RPM</span></span>
        </div>
        
        <div class="h-4 w-full bg-(--bg-secondary) rounded-sm border border-(--border-primary) flex p-0.5 overflow-hidden">
          <div 
            class="h-full bg-linear-to-r from-warning to-primary transition-all duration-300 relative"
            :style="{ width: `${side === 'Left' ? thrusterL : thrusterR}%` }"
          >
             <div class="absolute inset-0 bg-white/20 animate-pulse"></div>
          </div>
        </div>
        
        <div class="flex justify-between text-[8px] font-black text-(--text-muted) uppercase">
          <span>0%</span>
          <span>50%</span>
          <span>100%</span>
        </div>
      </div>
    </div>
  </div>
</template>
