<script setup>
import { computed } from 'vue';

const props = defineProps({
  pitch: { type: Number, default: 0 },
  roll: { type: Number, default: 0 }
});

// Transform values for SVG
const rollRotation = computed(() => `rotate(${-props.roll}, 100, 100)`);
const pitchTranslation = computed(() => `translate(0, ${props.pitch * 2})`);
</script>

<template>
  <div class="relative w-full aspect-square max-w-[240px] mx-auto bg-(--bg-secondary) rounded-full border-4 border-(--border-subtle) shadow-2xl overflow-hidden group">
    <!-- Sky & Ground -->
    <svg viewBox="0 0 200 200" class="w-full h-full transition-transform duration-100 ease-out shadow-inner" :transform="rollRotation">
      <defs>
        <linearGradient id="skyGradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" style="stop-color:#0077be;stop-opacity:1" />
          <stop offset="100%" style="stop-color:#38bdf8;stop-opacity:1" />
        </linearGradient>
        <linearGradient id="groundGradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" style="stop-color:#5d4037;stop-opacity:1" />
          <stop offset="100%" style="stop-color:#3e2723;stop-opacity:1" />
        </linearGradient>
      </defs>
      <g :transform="pitchTranslation">
        <!-- Sky -->
        <rect x="-100" y="-300" width="400" height="400" fill="url(#skyGradient)" />
        <!-- Ground -->
        <rect x="-100" y="100" width="400" height="400" fill="url(#groundGradient)" />
        <!-- Horizon Line -->
        <line x1="-100" y1="100" x2="300" y2="100" class="stroke-(--text-primary)" stroke-width="2" />
        
        <!-- Pitch Ladder -->
        <g class="stroke-(--text-primary)" stroke-width="1.5" opacity="0.8" font-family="monospace" font-size="8" font-weight="bold">
          <!-- 20 up -->
          <line x1="70" y1="60" x2="130" y2="60" />
          <text x="65" y="63" text-anchor="end" class="fill-(--text-primary)" stroke="none">20</text>
          <text x="135" y="63" text-anchor="start" class="fill-(--text-primary)" stroke="none">20</text>
          
          <!-- 10 up -->
          <line x1="85" y1="80" x2="115" y2="80" />
          <text x="80" y="83" text-anchor="end" class="fill-(--text-primary)" stroke="none">10</text>
          <text x="120" y="83" text-anchor="start" class="fill-(--text-primary)" stroke="none">10</text>
          
          <!-- 10 down -->
          <line x1="85" y1="120" x2="115" y2="120" />
          <text x="80" y="123" text-anchor="end" class="fill-(--text-primary)" stroke="none">10</text>
          <text x="120" y="123" text-anchor="start" class="fill-(--text-primary)" stroke="none">10</text>
          
          <!-- 20 down -->
          <line x1="70" y1="140" x2="130" y2="140" />
          <text x="65" y="143" text-anchor="end" class="fill-(--text-primary)" stroke="none">20</text>
          <text x="135" y="143" text-anchor="start" class="fill-(--text-primary)" stroke="none">20</text>
        </g>
      </g>
    </svg>

    <!-- Fixed Frame Overlay -->
    <div class="absolute inset-0 border-12 border-(--bg-secondary) rounded-full pointer-events-none shadow-[inset_0_0_20px_rgba(0,0,0,0.5)]"></div>

    <!-- Fixed Vessel Indicator (Center) -->
    <div class="absolute inset-0 flex items-center justify-center pointer-events-none">
      <svg viewBox="0 0 200 200" class="w-full h-full">
        <!-- Wings / Reference Line -->
        <path d="M 40 100 L 85 100 L 100 115 L 115 100 L 160 100" fill="none" class="stroke-(--status-error)" stroke-width="4" stroke-linecap="square" />
        <circle cx="100" cy="100" r="4" class="fill-(--status-error)" />
      </svg>
    </div>

    <!-- Readout Overlays -->
    <div class="absolute bottom-6 left-0 right-0 flex justify-center gap-3">
      <div class="flex flex-col items-center bg-black/60 backdrop-blur-md px-3 py-1 rounded-lg border border-white/10">
        <span class="text-[8px] text-white/50 uppercase font-black">Pitch</span>
        <span class="text-xs font-mono font-black text-white">{{ pitch.toFixed(2) }}°</span>
      </div>
      <div class="flex flex-col items-center bg-black/60 backdrop-blur-md px-3 py-1 rounded-lg border border-white/10">
        <span class="text-[8px] text-white/50 uppercase font-black">Roll</span>
        <span class="text-xs font-mono font-black text-white">{{ roll.toFixed(2) }}°</span>
      </div>
    </div>
  </div>
</template>
