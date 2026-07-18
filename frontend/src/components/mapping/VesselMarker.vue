<script setup>
defineProps({
  heading: { type: Number, default: 0 },
  color: { type: String, default: '#38bdf8' }
});
</script>

<template>
  <div class="relative w-10 h-10 flex items-center justify-center transition-transform duration-300" :style="{ transform: `rotate(${heading}deg)` }">
    <svg viewBox="0 0 100 100" class="w-full h-full drop-shadow-[0_0_8px_rgba(56,189,248,0.5)">
      <path d="M 50 10 L 80 80 L 50 65 L 20 80 Z" :fill="color" stroke="white" stroke-width="4" stroke-linejoin="round" />
      <circle cx="50" cy="50" r="5" fill="white" />
    </svg>
    <!-- Heading indicator line -->
    <div class="absolute top-0 left-1/2 -ml-px w-0.5 h-12 bg-primary/40 -translate-y-1/2"></div>
  </div>
</template>
