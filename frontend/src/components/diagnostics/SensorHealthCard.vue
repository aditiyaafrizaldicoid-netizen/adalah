<script setup>
import { CheckCircle2, AlertCircle, XCircle, Activity } from 'lucide-vue-next';

defineProps({
  name: String,
  status: String, // success, warning, danger
  value: String,
  lastUpdate: String
});
</script>

<template>
  <div :class="[
    'glass-card p-5 border-l-4 transition-all hover:scale-[1.02]',
    status === 'success' ? 'border-l-success' : status === 'warning' ? 'border-l-warning' : 'border-l-danger'
  ]">
    <div class="flex justify-between items-start mb-3">
      <span class="text-[10px] font-black text-(--text-primary) uppercase tracking-widest">{{ name }}</span>
      <component :is="status === 'success' ? CheckCircle2 : status === 'warning' ? AlertCircle : XCircle" 
        :class="['w-4 h-4', status === 'success' ? 'text-success' : status === 'warning' ? 'text-warning' : 'text-danger']" />
    </div>
    <div class="flex flex-col">
      <span :class="['text-lg font-black font-mono tracking-tight', status === 'success' ? 'text-success/80' : status === 'warning' ? 'text-warning/80' : 'text-danger/80']">
        {{ value }}
      </span>
      <div class="flex items-center gap-2 mt-2">
         <Activity class="w-3 h-3 text-(--text-muted)" />
         <span class="text-[8px] text-(--text-secondary) font-bold uppercase tracking-widest">LAST UPDATE: {{ lastUpdate }}</span>
      </div>
    </div>
  </div>
</template>
