<script setup>
import { computed } from 'vue';

const props = defineProps({
  speed: { type: Number, default: 0 },
  max: { type: Number, default: 10 }
});

const percentage = computed(() => Math.min(100, (props.speed / props.max) * 100));
const rotation = computed(() => -90 + (percentage.value * 1.8)); // -90 to 90 degrees
</script>

<template>
  <div class="flex flex-col items-center">
    <div class="relative w-40 h-24 overflow-hidden">
      <!-- Gauge Background -->
      <svg viewBox="0 0 100 60" class="w-full h-full">
        <!-- Outer Track -->
        <path d="M 10 50 A 40 40 0 0 1 90 50" fill="none" class="stroke-(--border-primary)" stroke-width="10" stroke-linecap="round" />
        
        <!-- Animated Progress -->
        <path 
          d="M 10 50 A 40 40 0 0 1 90 50" 
          fill="none" 
          class="stroke-primary transition-all duration-700 ease-out" 
          stroke-width="10" 
          stroke-linecap="round"
          :stroke-dasharray="`${(percentage / 100) * 125.6} 125.6`"
          filter="drop-shadow(0 0 3px rgba(200, 16, 46, 0.4))"
        />
        
        <!-- Ticks -->
        <g class="stroke-(--border-subtle)" stroke-width="1">
          <line v-for="i in 11" :key="i" x1="100" y1="10" x2="100" y2="15" :transform="`rotate(${-90 + (i-1)*18}, 50, 50)`" />
        </g>
      </svg>
      
      <!-- Center Readout Overlay -->
      <div class="absolute inset-0 flex flex-col items-center justify-end pb-2">
        <span class="text-2xl font-black text-(--text-primary) font-mono leading-none tracking-tighter">{{ speed.toFixed(2) }}</span>
        <span class="text-[9px] font-black text-primary uppercase tracking-widest">Knots</span>
      </div>
    </div>
  </div>
</template>
