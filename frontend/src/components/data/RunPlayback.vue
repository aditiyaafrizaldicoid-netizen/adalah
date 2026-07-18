<script setup>
import { Play, Pause, SkipBack, SkipForward, FastForward } from 'lucide-vue-next';
import { ref } from 'vue';

const isPlaying = ref(false);
const progress = ref(30);
const playbackSpeed = ref(1);
</script>

<template>
  <div class="glass-card p-6 space-y-6 border-t-4 border-t-primary">
    <div class="flex flex-col items-center gap-4">
       <!-- Timeline Slider -->
       <div class="w-full space-y-2">
          <div class="flex justify-between text-[10px] font-black font-mono text-(--text-secondary) uppercase tracking-widest">
             <span>00:00</span>
             <span class="text-primary font-bold">REPLAYING: 04:12 / 12:45</span>
             <span>12:45</span>
          </div>
          <input v-model="progress" type="range" class="w-full accent-primary h-2 bg-card rounded-full appearance-none cursor-pointer" />
       </div>

       <!-- Controls -->
       <div class="flex items-center gap-8">
          <button class="text-(--text-secondary) hover:text-(--text-primary) transition-colors"><SkipBack class="w-6 h-6" /></button>
          <button @click="isPlaying = !isPlaying" class="w-16 h-16 bg-primary text-slate-900 rounded-full flex items-center justify-center shadow-xl shadow-primary/20 hover:scale-110 transition-all">
             <component :is="isPlaying ? Pause : Play" class="w-8 h-8 fill-current" />
          </button>
          <button class="text-(--text-secondary) hover:text-(--text-primary) transition-colors"><SkipForward class="w-6 h-6" /></button>
       </div>

       <!-- Speed Selector -->
       <div class="flex gap-2">
          <button 
            v-for="s in [1, 2, 4, 8]" 
            :key="s"
            @click="playbackSpeed = s"
            :class="['px-4 py-1.5 rounded-full text-[10px] font-black transition-all border', playbackSpeed === s ? 'bg-primary text-slate-900 border-primary' : 'bg-card text-(--text-secondary) border-(--border-subtle)']"
          >
            {{ s }}X
          </button>
       </div>
    </div>
  </div>
</template>
