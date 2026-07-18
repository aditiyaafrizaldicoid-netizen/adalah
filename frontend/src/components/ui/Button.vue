<script setup>
defineProps({
  variant: { type: String, default: 'primary' }, // primary, danger, ghost, outline
  size: { type: String, default: 'md' }, // sm, md, lg
  loading: Boolean,
  disabled: Boolean,
  icon: Object
});
</script>

<template>
  <button
    :disabled="disabled || loading"
    :class="[
      'inline-flex items-center justify-center gap-2 font-bold uppercase tracking-widest transition-all active:scale-95 disabled:opacity-50 disabled:active:scale-100',
      size === 'sm' ? 'px-3 py-1.5 text-[10px] rounded-lg' :
      size === 'md' ? 'px-5 py-2.5 text-xs rounded-xl' :
      'px-8 py-3 text-sm rounded-2xl',
      variant === 'primary' ? 'bg-primary text-slate-900 hover:bg-sky-400 shadow-lg shadow-primary/20' :
      variant === 'danger' ? 'bg-danger text-(--text-primary) hover:bg-red-600 shadow-lg shadow-danger/20' :
      variant === 'outline' ? 'border-2 border-(--border-subtle) text-(--text-primary) hover:border-primary hover:text-(--text-primary)' :
      'bg-transparent text-(--text-secondary) hover:bg-card hover:text-(--text-primary)'
    ]"
  >
    <component v-if="icon && !loading" :is="icon" class="w-4 h-4" />
    <div v-if="loading" class="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></div>
    <slot />
  </button>
</template>
