<script setup>
defineProps({
  points: { type: Array, default: () => [] },
  color: { type: String, default: '#38bdf8' }
});
</script>

<template>
  <!-- Logic-only component for Canvas/SVG trail rendering -->
  <div class="hidden">
    <!-- Trail rendering would typically happen in the parent Canvas, but we keep this file for modularity -->
  </div>
</template>
