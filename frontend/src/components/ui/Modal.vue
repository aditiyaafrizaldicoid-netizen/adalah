<script setup>
import { X } from 'lucide-vue-next';

defineProps({
  show: Boolean,
  title: String,
  size: { type: String, default: 'md' } // sm, md, lg, xl
});

defineEmits(['close']);
</script>

<template>
  <transition
    enter-active-class="transition duration-300 ease-out"
    enter-from-class="opacity-0 scale-95"
    enter-to-class="opacity-100 scale-100"
    leave-active-class="transition duration-200 ease-in"
    leave-from-class="opacity-100 scale-100"
    leave-to-class="opacity-0 scale-95"
  >
    <div v-if="show" class="fixed inset-0 z-100 flex items-center justify-center p-6">
      <!-- Backdrop -->
      <div class="absolute inset-0 bg-background/80 backdrop-blur-sm" @click="$emit('close')"></div>
      
      <!-- Content -->
      <div :class="[
        'relative bg-secondary border border-(--border-subtle)/50 rounded-2xl shadow-2xl flex flex-col overflow-hidden max-h-full',
        size === 'sm' ? 'w-full max-w-sm' :
        size === 'md' ? 'w-full max-w-lg' :
        size === 'lg' ? 'w-full max-w-2xl' : 'w-full max-w-4xl'
      ]">
        <div class="flex items-center justify-between p-6 border-b border-(--border-primary)">
          <h3 class="text-lg font-bold text-(--text-primary) uppercase tracking-wider">{{ title }}</h3>
          <button @click="$emit('close')" class="p-2 hover:bg-card rounded-lg text-(--text-secondary) transition-colors">
            <X class="w-5 h-5" />
          </button>
        </div>
        
        <div class="p-6 overflow-y-auto">
          <slot />
        </div>
        
        <div v-if="$slots.footer" class="p-6 border-t border-(--border-primary) bg-(--bg-secondary)/50 flex justify-end gap-3">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </transition>
</template>
