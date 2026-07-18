<script setup>
defineProps({
  type: { type: String, default: 'red' }, // red, green, blue
  label: String,
  passed: Boolean
});
</script>

<template>
  <div class="flex flex-col items-center gap-1 group cursor-pointer">
    <div :class="[
      'w-4 h-4 rounded-full border-2 transition-all',
      type === 'red' ? 'border-danger' : type === 'green' ? 'border-success' : 'border-primary',
      passed ? (type === 'red' ? 'bg-danger shadow-[0_0_10px_#ef4444]' : type === 'green' ? 'bg-success shadow-[0_0_10px_#22c55e]' : 'bg-primary shadow-[0_0_10px_#38bdf8]') : 'bg-transparent'
    ]"></div>
    <span v-if="label" class="text-[8px] font-black text-(--text-secondary) uppercase tracking-tighter group-hover:text-(--text-primary) transition-colors">{{ label }}</span>
  </div>
</template>
