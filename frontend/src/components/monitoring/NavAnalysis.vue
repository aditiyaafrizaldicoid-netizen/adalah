<script setup>
import { ArrowUpRight, Navigation, Target } from 'lucide-vue-next';
import { computed } from 'vue';

const props = defineProps({
  xte: { type: Number, default: 0 }, // Cross Track Error in meters
  dtw: { type: Number, default: 0 }, // Distance to Waypoint in meters
  nextWp: { type: Number, default: 1 }
});

const xteStatus = computed(() => {
  if (Math.abs(props.xte) < 0.5) return 'text-success';
  if (Math.abs(props.xte) < 2.0) return 'text-warning';
  return 'text-danger';
});
</script>

<template>
  <div class="glass-card p-5 space-y-6 overflow-hidden relative">
    <div class="flex items-center gap-3">
       <Navigation class="w-5 h-5 text-primary" />
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Navigation Analysis</span>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <!-- XTE Indicator -->
      <div class="flex flex-col gap-2">
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest">Cross-Track Error</span>
        <div class="flex items-baseline gap-1">
          <span :class="['text-2xl font-black font-mono', xteStatus]">{{ xte.toFixed(2) }}</span>
          <span class="text-[10px] font-bold text-(--text-secondary)">MTRS</span>
        </div>
        <!-- Visual XTE Bar -->
        <div class="h-2 w-full bg-(--bg-secondary) rounded-full relative overflow-hidden border border-(--border-primary)">
          <div 
            class="absolute top-0 bottom-0 w-1 bg-primary left-1/2 -ml-0.5 shadow-[0_0_5px_rgba(200,16,46,0.5)]"
            :style="{ transform: `translateX(${xte * 10}px)` }"
          ></div>
          <div class="absolute inset-0 flex justify-center items-center pointer-events-none">
            <div class="w-px h-full bg-white/10"></div>
          </div>
        </div>
      </div>

      <!-- DTW Info -->
      <div class="flex flex-col gap-2">
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest">To Waypoint #{{ nextWp }}</span>
        <div class="flex items-baseline gap-1">
          <span class="text-2xl font-black text-(--text-primary) font-mono">{{ dtw.toFixed(2) }}</span>
          <span class="text-[10px] font-bold text-(--text-secondary)">MTRS</span>
        </div>
        <div class="flex items-center gap-2 text-[10px] font-bold text-success uppercase">
           <Target class="w-3 h-3" />
           ETA: {{ (dtw / 2.5).toFixed(1) }}s
        </div>
      </div>
    </div>
    
    <!-- Background Decor -->
    <ArrowUpRight class="absolute -right-4 -bottom-4 w-24 h-24 text-primary opacity-5 rotate-45" />
  </div>
</template>
