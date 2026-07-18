<script setup>
defineProps({
  modelValue: Boolean,
  label: String
});
defineEmits(['update:modelValue']);
</script>

<template>
  <label class="flex items-center gap-3 cursor-pointer group">
    <span v-if="label" class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest">{{ label }}</span>
    <div 
      @click="$emit('update:modelValue', !modelValue)"
      :class="['w-10 h-5 rounded-full relative transition-all duration-300', modelValue ? 'bg-primary shadow-[0_0_10px_rgba(56,189,248,0.4)' : 'bg-(--bg-secondary)']"
    >
      <div :class="['absolute top-1 w-3 h-3 rounded-full bg-white transition-all duration-300 shadow-md', modelValue ? 'left-6' : 'left-1']"></div>
    </div>
  </label>
</template>
