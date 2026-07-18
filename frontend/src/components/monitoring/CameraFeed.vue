<script setup>
import { Camera, RefreshCw, Maximize2 } from 'lucide-vue-next';

defineProps({
  label: String,
  streamUrl: { type: String, default: 'http://localhost:3000/api/v1/video/stream' },
  status: { type: String, default: 'CONNECTED' }
});
</script>

<template>
  <div class="glass-card aspect-video relative overflow-hidden group">
    <!-- Camera Overlay -->
    <div class="absolute inset-0 bg-(--bg-secondary) flex flex-col items-center justify-center">
      <Camera class="w-12 h-12 text-slate-800" />
      <img :src="streamUrl" class="w-full h-full object-cover"
        onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
        onload="this.style.display='block'; this.nextElementSibling.style.display='none';" />
    </div>

    <!-- Top Bar Overlay -->
    <div
      class="absolute top-0 left-0 right-0 p-3 flex justify-between items-center bg-linear-to-b from-slate-950/80 to-transparent">
      <div class="flex items-center gap-2">
        <div :class="['w-2 h-2 rounded-full', status === 'CONNECTED' ? 'bg-success animate-pulse' : 'bg-danger']"></div>
        <span class="text-[10px] font-black text-(--text-primary) uppercase tracking-widest">{{ label }}</span>
      </div>
      <div class="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <button class="p-1.5 bg-card/80 rounded hover:bg-primary hover:text-slate-900 transition-all">
          <RefreshCw class="w-3.5 h-3.5" />
        </button>
        <button class="p-1.5 bg-card/80 rounded hover:bg-primary hover:text-slate-900 transition-all">
          <Maximize2 class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- Bottom Stats Overlay -->
    <div class="absolute bottom-3 left-3 text-[10px] font-mono text-(--text-secondary) opacity-60">
      {{ status === 'CONNECTED' ? '1280x720 @ 30FPS | 2.4Mbps' : 'OFFLINE' }}
    </div>
  </div>
</template>
