<script setup>
import { AlertCircle, X, CheckCircle, Info, ShieldAlert } from 'lucide-vue-next';

defineProps({
  type: { type: String, default: 'info' }, // info, success, warning, danger
  message: String,
  showClose: { type: Boolean, default: true }
});

const icons = {
  info: Info,
  success: CheckCircle,
  warning: AlertCircle,
  danger: ShieldAlert
};
</script>

<template>
  <div :class="[
    'flex items-center gap-4 p-4 rounded-xl border animate-in slide-in-from-top duration-300',
    type === 'info' ? 'bg-primary/10 border-primary/20 text-primary' :
    type === 'success' ? 'bg-success/10 border-success/20 text-success' :
    type === 'warning' ? 'bg-warning/10 border-warning/20 text-warning' :
    'bg-danger/10 border-danger/20 text-danger'
  ]">
    <component :is="icons[type]" class="w-5 h-5 shrink-0" />
    <span class="text-sm font-semibold flex-1">{{ message }}</span>
    <button v-if="showClose" class="hover:opacity-70 transition-opacity">
      <X class="w-4 h-4" />
    </button>
  </div>
</template>
