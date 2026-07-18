<script setup>
import { Zap, SlidersHorizontal, ArrowUp, ArrowDown } from 'lucide-vue-next';
import { ref } from 'vue';

const thrusterL = ref(0);
const thrusterR = ref(0);
</script>

<template>
   <div class="space-y-6">
      <div class="grid grid-cols-2 gap-6">
         <div v-for="side in ['Left', 'Right']" :key="side" class="glass-card p-6 flex flex-col items-center">
            <span class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest mb-6">{{ side }} Thruster
               Test</span>

            <div class="h-48 w-8 bg-(--bg-secondary) rounded-full relative overflow-hidden border border-(--border-primary)">
               <div class="absolute bottom-0 w-full bg-primary transition-all duration-150"
                  :style="{ height: `${side === 'Left' ? thrusterL : thrusterR}%` }"></div>
            </div>

            <div class="mt-4 text-xl font-black text-(--text-primary) font-mono">{{ side === 'Left' ? thrusterL : thrusterR }}%
            </div>

            <input :value="side === 'Left' ? thrusterL : thrusterR" 
               @input="e => side === 'Left' ? thrusterL = Number(e.target.value) : thrusterR = Number(e.target.value)" 
               type="range" orient="vertical" class="mt-4 w-full" />
         </div>
      </div>

      <div class="glass-card p-6 border-l-4 border-l-warning">
         <div class="flex items-center gap-3 mb-6">
            <SlidersHorizontal class="w-5 h-5 text-warning" />
            <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Trim & Balance Adjustment</span>
         </div>

         <div class="space-y-6 max-w-md">
            <div class="flex items-center gap-6">
               <span class="text-[10px] font-bold text-(--text-secondary) uppercase w-24">Port Offset</span>
               <input type="range" class="flex-1 accent-warning" />
               <span class="text-xs font-mono text-warning">-2.4%</span>
            </div>
            <div class="flex items-center gap-6">
               <span class="text-[10px] font-bold text-(--text-secondary) uppercase w-24">Starboard Offset</span>
               <input type="range" class="flex-1 accent-warning" />
               <span class="text-xs font-mono text-warning">+1.2%</span>
            </div>
         </div>
      </div>
   </div>
</template>
