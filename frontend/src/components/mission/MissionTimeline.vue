<script setup>
import { CheckCircle2, Circle, Clock } from 'lucide-vue-next';

defineProps({
  steps: Array,
  currentStep: Number
});
</script>

<template>
  <div class="relative flex flex-col gap-6">
    <!-- Vertical Line -->
    <div class="absolute left-5 top-2 bottom-2 w-0.5 bg-card"></div>
    
    <div v-for="step in steps" :key="step.id" class="relative flex items-center gap-6 group">
      <div :class="[
        'w-10 h-10 rounded-full flex items-center justify-center z-10 transition-all border-4 border-background',
        currentStep > step.id ? 'bg-success text-slate-900' : 
        currentStep === step.id ? 'bg-primary text-slate-900 ring-4 ring-primary/20' : 'bg-card text-(--text-secondary)'
      ]">
        <CheckCircle2 v-if="currentStep > step.id" class="w-5 h-5" />
        <span v-else class="text-xs font-black">{{ step.id }}</span>
      </div>
      
      <div class="flex-1">
        <h4 :class="['text-xs font-black uppercase tracking-widest', currentStep === step.id ? 'text-(--text-primary)' : 'text-(--text-secondary)']">
          {{ step.name }}
        </h4>
        <div v-if="currentStep === step.id" class="flex items-center gap-2 mt-1">
          <Clock class="w-3 h-3 text-primary animate-pulse" />
          <span class="text-[10px] font-mono text-primary/70">In Progress...</span>
        </div>
      </div>
    </div>
  </div>
</template>
