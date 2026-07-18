<script setup>
import { computed } from 'vue';
import { Maximize2, RefreshCw, AlertCircle } from 'lucide-vue-next';
import { useMjpegStream } from '@/composables/useMjpegStream';

const videoUrl = import.meta.env.VITE_VIDEO_FEED_URL;
const srcRef = computed(() => videoUrl || null);
const { activeSrc, isError, onError, onLoad, reload, imgRef, BLANK } = useMjpegStream(srcRef);
</script>

<template>
  <div class="bg-zinc-900 rounded-2xl border border-zinc-800 overflow-hidden flex flex-col shadow-xl">
    <div class="px-6 py-4 border-b border-zinc-800 flex justify-between items-center bg-zinc-900/50">
      <div class="flex items-center gap-2">
        <div :class="['w-2 h-2 rounded-full', isError ? 'bg-red-500' : 'bg-green-500 animate-pulse']"></div>
        <h3 class="font-bold text-zinc-100">Live Calibration Feed</h3>
      </div>
      <div class="flex gap-2">
        <button @click="reload" class="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-all">
          <RefreshCw class="w-4 h-4" />
        </button>
        <button class="p-2 text-zinc-400 hover:text-white hover:bg-zinc-800 rounded-lg transition-all">
          <Maximize2 class="w-4 h-4" />
        </button>
      </div>
    </div>

    <div class="relative aspect-video bg-black group flex items-center justify-center">
      <img
        ref="imgRef"
        :src="activeSrc"
        @error="onError"
        @load="onLoad"
        class="w-full h-full object-contain"
        :class="{ 'opacity-0': isError || activeSrc === BLANK }"
      />

      <div v-if="isError || !videoUrl"
        class="absolute inset-0 flex flex-col items-center gap-3 text-zinc-500 p-8 text-center justify-center">
        <AlertCircle class="w-12 h-12 text-zinc-700" />
        <div>
          <p class="font-bold text-zinc-300">Feed Unavailable</p>
          <p class="text-xs">Make sure the backend is online at <br /> {{ videoUrl }}</p>
        </div>
        <button @click="reload"
          class="mt-2 px-4 py-2 bg-zinc-800 text-zinc-100 rounded-lg hover:bg-zinc-700 text-sm font-medium transition-all">
          Retry Connection
        </button>
      </div>

      <div class="absolute bottom-4 left-4 flex gap-2">
        <span class="px-2 py-1 bg-black/60 backdrop-blur-md rounded text-[10px] font-bold text-white uppercase">720p</span>
        <span :class="['px-2 py-1 bg-black/60 backdrop-blur-md rounded text-[10px] font-bold uppercase', isError ? 'text-red-400' : 'text-green-500']">
          {{ isError ? 'Reconnecting' : 'Live' }}
        </span>
      </div>
    </div>
  </div>
</template>