<script setup>
defineProps({
  label: String,
  value: String,
  status: {
    type: String,
    default: 'info' // success, warning, danger, info
  }
});
</script>

<template>
  <div class="flex items-center gap-2 bg-card/80 border border-(--border-subtle) p-1 pl-3 rounded-lg overflow-hidden">
    <span class="text-[10px] font-black text-(--text-secondary) uppercase tracking-tighter">{{ label }}</span>
    <div :class="[
      'px-2 py-0.5 rounded text-[10px] font-black uppercase tracking-widest',
      status === 'success' ? 'bg-success/20 text-success' :
      status === 'warning' ? 'bg-warning/20 text-warning' :
      status === 'danger' ? 'bg-danger/20 text-danger' :
      'bg-primary/20 text-primary'
    ]">
      {{ value }}
    </div>
  </div>
</template>
