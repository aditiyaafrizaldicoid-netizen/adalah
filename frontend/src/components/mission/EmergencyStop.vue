<script setup>
import { Zap } from 'lucide-vue-next';

defineEmits(['stop']);
</script>

<template>
  <button 
    @click="$emit('stop')"
    class="relative group w-full bg-danger hover:bg-red-600 text-(--text-primary) p-6 rounded-2xl flex flex-col items-center justify-center gap-3 transition-all active:scale-95 shadow-2xl shadow-danger/30 overflow-hidden"
  >
    <!-- Pulse Effect -->
    <div class="absolute inset-0 bg-white/20 animate-ping rounded-full scale-50 opacity-0 group-hover:opacity-100"></div>
    
    <div class="w-16 h-16 bg-white/20 rounded-full flex items-center justify-center relative z-10">
      <Zap class="w-10 h-10 fill-current" />
    </div>
    
    <div class="text-center relative z-10">
      <h2 class="text-2xl font-black uppercase tracking-tighter leading-none">KILL SWITCH</h2>
      <p class="text-[10px] font-bold text-(--text-primary)/60 uppercase tracking-widest mt-1">Immediate Thruster Stop</p>
    </div>
  </button>
</template>
