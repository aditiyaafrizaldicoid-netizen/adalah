<script setup>
import { computed } from 'vue';

const props = defineProps({
  pitch: { type: Number, default: 0 },
  roll: { type: Number, default: 0 }
});

// Style CSS transform dipakai (bukan atribut SVG `transform` di root <svg>),
// karena atribut transform pada elemen <svg> terluar tidak reliable di semua
// browser (spec-nya cuma valid untuk elemen grafis seperti <g>, <path>, dst).
const horizonStyle = computed(() => ({
  transform: `rotate(${-props.roll}deg) translateY(${props.pitch * 2}px)`,
  transformOrigin: '100px 100px'
}));

const pointerStyle = computed(() => ({
  transform: `rotate(${-props.roll}deg)`,
  transformOrigin: '100px 100px'
}));

const clampedPitch = computed(() => Math.max(-90, Math.min(90, props.pitch)));
</script>

<template>
  <!-- Main Bezel Frame -->
  <div class="relative w-full aspect-square max-w-[280px] mx-auto rounded-full
           bg-gradient-to-b from-slate-700 via-slate-900 to-black
           shadow-[0_20px_45px_-10px_rgba(0,0,0,0.7)]
           p-[10px] ring-1 ring-black/60">
    <!-- Inner recessed housing -->
    <div class="relative w-full h-full rounded-full overflow-hidden
                bg-slate-950 shadow-[inset_0_2px_6px_rgba(255,255,255,0.15),inset_0_-4px_10px_rgba(0,0,0,0.9)]">

      <!-- 1. Moving Horizon (Sky & Sea) -->
      <svg viewBox="0 0 200 200" class="absolute inset-0 w-full h-full">
        <defs>
          <linearGradient id="skyGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#1E88E5" />
            <stop offset="100%" stop-color="#90CAF9" />
          </linearGradient>
          <linearGradient id="seaGrad" x1="0%" y1="0%" x2="0%" y2="100%">
            <stop offset="0%" stop-color="#00897B" />
            <stop offset="100%" stop-color="#002622" />
          </linearGradient>
        </defs>

        <g :style="horizonStyle" style="transition: transform 0.12s ease-out;">
          <!-- Sky & Sea -->
          <rect x="-200" y="-400" width="600" height="500" fill="url(#skyGrad)" />
          <rect x="-200" y="100" width="600" height="500" fill="url(#seaGrad)" />
          <!-- Horizon Line -->
          <line x1="-200" y1="100" x2="400" y2="100" stroke="#FFFFFF" stroke-width="2.5" />

          <!-- Pitch Ladder -->
          <g stroke="#FFFFFF" stroke-width="1.5" opacity="0.9" font-family="ui-monospace, monospace" font-size="7.5"
            font-weight="700" fill="#FFFFFF" stroke-linecap="round">
            <line x1="75" y1="75" x2="125" y2="75" />
            <text x="67" y="78" text-anchor="end">10</text>
            <text x="133" y="78" text-anchor="start">10</text>

            <line x1="80" y1="50" x2="120" y2="50" />
            <text x="72" y="53" text-anchor="end">20</text>
            <text x="128" y="53" text-anchor="start">20</text>

            <line x1="85" y1="25" x2="115" y2="25" />
            <text x="77" y="28" text-anchor="end">30</text>
            <text x="123" y="28" text-anchor="start">30</text>

            <line x1="75" y1="125" x2="125" y2="125" stroke-dasharray="4 3" />
            <text x="67" y="128" text-anchor="end">10</text>
            <text x="133" y="128" text-anchor="start">10</text>

            <line x1="80" y1="150" x2="120" y2="150" stroke-dasharray="4 3" />
            <text x="72" y="153" text-anchor="end">20</text>
            <text x="128" y="153" text-anchor="start">20</text>

            <line x1="85" y1="175" x2="115" y2="175" stroke-dasharray="4 3" />
            <text x="77" y="178" text-anchor="end">30</text>
            <text x="123" y="178" text-anchor="start">30</text>
          </g>
        </g>
      </svg>

      <!-- 2. Static Overlay (Bank Scale + Crosshair) -->
      <svg viewBox="0 0 200 200" class="absolute inset-0 w-full h-full pointer-events-none">
        <path d="M 26 60 A 85 85 0 0 1 174 60" fill="none" stroke="#F5F5F5" stroke-width="2" opacity="0.95"
          stroke-linecap="round" />

        <g stroke="#F5F5F5" stroke-width="2.5" opacity="0.95" stroke-linecap="round">
          <line x1="100" y1="15" x2="100" y2="25" />
          <line x1="85.2" y1="16.3" x2="87.0" y2="26.1" />
          <line x1="114.8" y1="16.3" x2="113.0" y2="26.1" />
          <line x1="70.9" y1="20.1" x2="74.3" y2="29.5" />
          <line x1="129.1" y1="20.1" x2="125.7" y2="29.5" />
          <line x1="57.5" y1="26.4" x2="65.0" y2="39.4" stroke-width="3" />
          <line x1="142.5" y1="26.4" x2="135.0" y2="39.4" stroke-width="3" />
          <line x1="39.9" y1="39.9" x2="47.0" y2="47.0" />
          <line x1="160.1" y1="39.9" x2="153.0" y2="47.0" />
          <line x1="26.4" y1="57.5" x2="35.0" y2="62.5" stroke-width="3" />
          <line x1="173.6" y1="57.5" x2="165.0" y2="62.5" stroke-width="3" />
        </g>

        <!-- Ship / Aircraft Crosshair -->
        <g stroke="#FFC107" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round" fill="none">
          <circle cx="100" cy="100" r="3.5" fill="#FFC107" stroke="none" />
          <path d="M 35 100 L 75 100 L 75 108" />
          <path d="M 165 100 L 125 100 L 125 108" />
        </g>
      </svg>

      <!-- Bank Angle Pointer -->
      <svg viewBox="0 0 200 200" class="absolute inset-0 w-full h-full pointer-events-none">
        <g :style="pointerStyle" style="transition: transform 0.12s ease-out;">
          <polygon points="100,27 94,37 106,37" fill="#FFC107" stroke="#1A1A2E" stroke-width="1" />
        </g>
      </svg>

      <!-- Glass reflection -->
      <div class="absolute inset-0 rounded-full pointer-events-none"
        style="background: radial-gradient(circle at 32% 28%, rgba(255,255,255,0.30) 0%, rgba(255,255,255,0.08) 32%, rgba(255,255,255,0) 58%);">
      </div>
      <!-- Inner rim shading -->
      <div class="absolute inset-0 rounded-full pointer-events-none shadow-[inset_0_0_18px_rgba(0,0,0,0.85)]"></div>
    </div>

    <!-- Readouts -->
    <div class="absolute -bottom-3 left-0 right-0 flex justify-center gap-2">
      <div class="flex flex-col items-center bg-slate-900/95 backdrop-blur-sm px-3 py-1 rounded-md
                  shadow-[0_4px_10px_rgba(0,0,0,0.5)] border border-slate-700/80">
        <span class="text-[8.5px] text-slate-400 uppercase font-bold tracking-[0.15em] leading-none mb-0.5">Pitch</span>
        <span class="text-sm font-mono font-bold leading-none tabular-nums"
          :class="pitch > 0 ? 'text-sky-400' : (pitch < 0 ? 'text-teal-400' : 'text-slate-200')">
          {{ clampedPitch.toFixed(1) }}°
        </span>
      </div>
      <div class="flex flex-col items-center bg-slate-900/95 backdrop-blur-sm px-3 py-1 rounded-md
                  shadow-[0_4px_10px_rgba(0,0,0,0.5)] border border-slate-700/80">
        <span class="text-[8.5px] text-slate-400 uppercase font-bold tracking-[0.15em] leading-none mb-0.5">Roll</span>
        <span class="text-sm font-mono font-bold leading-none tabular-nums text-amber-400">
          {{ Math.abs(roll).toFixed(1) }}°
          <span class="text-[9px] text-slate-400 font-semibold">{{ roll > 0 ? 'R' : (roll < 0 ? 'L' : '') }}</span>
          </span>
      </div>
    </div>
  </div>
</template>