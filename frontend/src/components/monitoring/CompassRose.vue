<script setup>
import { computed } from 'vue';

const props = defineProps({
  heading: { type: Number, default: 0 }
});

const rotation = computed(() => `rotate(${-props.heading}, 100, 100)`);
</script>

<template>
  <div class="relative w-full aspect-square max-w-[240px] mx-auto bg-(--bg-secondary) rounded-full border-4 border-(--border-subtle) shadow-2xl overflow-hidden group">
    <!-- Bezel / Frame (Fixed) -->
    <div class="absolute inset-0 rounded-full border-16 border-(--bg-secondary) pointer-events-none shadow-2xl z-20"></div>
    
    <!-- Rotating Rose Group -->
    <svg viewBox="0 0 200 200" class="w-full h-full">
      <g :transform="rotation">
        <!-- Dial Background -->
        <circle cx="100" cy="100" r="90" class="fill-(--bg-card) stroke-(--border-primary)" stroke-width="2" />
        
        <!-- Markings -->
        <g class="fill-(--text-primary)" font-family="monospace" font-weight="900" font-size="16" style="pointer-events: none;">
          <text x="100" y="32" text-anchor="middle" class="fill-(--status-error)">N</text>
          <text x="168" y="105" text-anchor="middle">E</text>
          <text x="100" y="178" text-anchor="middle">S</text>
          <text x="32" y="105" text-anchor="middle">W</text>
        </g>

        <!-- Degree Marks -->
        <g class="stroke-(--text-secondary)" stroke-width="2">
          <line v-for="d in 12" :key="'tick-'+d" x1="100" y1="10" x2="100" y2="22" :transform="`rotate(${d * 30}, 100, 100)`" />
        </g>
        
        <g class="stroke-(--border-subtle)" stroke-width="1">
          <line v-for="d in 72" :key="'small-tick-'+d" x1="100" y1="10" x2="100" y2="16" :transform="`rotate(${d * 5}, 100, 100)`" />
        </g>
      </g>
    </svg>
    <div class="absolute inset-4 rounded-full border border-white/5 pointer-events-none"></div>

    <!-- Fixed Pointer (Lubber Line) -->
    <div class="absolute top-0 left-1/2 -ml-0.5 h-6 w-1 bg-(--status-error) rounded-b-full shadow-[0_0_10px_rgba(200,16,46,0.5)] z-30"></div>

    <!-- Center Readout -->
    <div class="absolute inset-0 flex items-center justify-center pointer-events-none z-40">
      <div class="bg-black/90 backdrop-blur-xl border border-white/10 w-20 h-20 rounded-full flex flex-col items-center justify-center shadow-2xl">
        <span class="text-[7px] text-white/40 uppercase font-black tracking-widest">Heading</span>
        <span class="text-lg font-black text-white font-mono leading-none">{{ heading.toFixed(2) }}°</span>
      </div>
    </div>
  </div>
</template>
