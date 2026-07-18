<script setup>
defineProps({
  progress: {
    type: Number,
    default: 0
  },
  color: {
    type: String,
    default: 'primary'
  }
});
</script>

<template>
  <div class="h-2 w-full bg-card rounded-full overflow-hidden border border-(--border-subtle)/50">
    <div 
      :class="[
        'h-full transition-all duration-1000 ease-out rounded-full relative',
        color === 'primary' ? 'bg-primary shadow-[0_0_10px_rgba(56,189,248,0.5)' :
        color === 'success' ? 'bg-success shadow-[0_0_10px_rgba(34,197,94,0.5)' :
        color === 'warning' ? 'bg-warning shadow-[0_0_10px_rgba(234,179,8,0.5)' :
        'bg-danger shadow-[0_0_10px_rgba(239,68,68,0.5)'
      ]"
      :style="{ width: `${progress}%` }"
    >
      <div class="absolute inset-0 bg-linear-to-r from-transparent to-white/20"></div>
    </div>
  </div>
</template>
