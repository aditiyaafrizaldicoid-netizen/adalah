<script setup>
import { ref, computed } from 'vue';
import { Camera, RefreshCw, Maximize2, Minimize2, Video, VideoOff, CircleDot } from 'lucide-vue-next';
import { useVesselStore } from '@/stores/vesselStore';
import { useWebsocketStore } from '@/stores/websocketStore';

const props = defineProps({
  label: String,
  streamUrl: { type: String, default: 'http://localhost:3000/api/v1/video/stream' },
  status: { type: String, default: 'CONNECTED' }
});

const vessel = useVesselStore();
const wsStore = useWebsocketStore();

const selectedRes = ref('640x480');
const streamKey = ref(0);            // increment → forces img reload
const containerRef = ref(null);      // ref to root div for fullscreen
const isFullscreen = ref(false);

// Append cache-busting param to MJPEG URL on every refresh
const liveStreamUrl = computed(() => `${props.streamUrl}?t=${streamKey.value}`);

function handleRefresh() {
  streamKey.value = Date.now();
}

function handleFullscreen() {
  if (!containerRef.value) return;
  if (!document.fullscreenElement) {
    containerRef.value.requestFullscreen().then(() => { isFullscreen.value = true; });
  } else {
    document.exitFullscreen().then(() => { isFullscreen.value = false; });
  }
}

const handleToggleRecord = () => {
  const [w, h] = selectedRes.value.split('x');
  wsStore.toggleRecording(parseInt(w), parseInt(h));
};
</script>

<template>
  <div ref="containerRef" class="glass-card aspect-video relative overflow-hidden group">
    <!-- Camera Overlay -->
    <div class="absolute inset-0 bg-(--bg-secondary) flex flex-col items-center justify-center">
      <Camera class="w-12 h-12 text-slate-800" />
      <img :src="liveStreamUrl" class="w-full h-full object-contain"
        onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
        onload="this.style.display='block'; this.nextElementSibling.style.display='none';" />
    </div>

    <!-- Top Bar Overlay -->
    <div
      class="absolute top-0 left-0 right-0 p-3 flex justify-between items-center bg-linear-to-b from-slate-950/80 to-transparent z-10">
      <div class="flex items-center gap-2">
        <div :class="['w-2 h-2 rounded-full', status === 'CONNECTED' ? 'bg-success animate-pulse' : 'bg-danger']"></div>
        <span class="text-[10px] font-black text-(--text-primary) uppercase tracking-widest">{{ label }}</span>
        
        <!-- Recording Indicator Badge -->
        <span v-if="vessel.isRecording"
          class="flex items-center gap-1 bg-red-600/90 text-white text-[10px] px-2 py-0.5 rounded font-black tracking-widest animate-pulse border border-red-400 shadow-lg">
          <CircleDot class="w-3 h-3 text-white" />
          REC {{ vessel.recordingResolution }}
        </span>
      </div>

      <!-- Controls: Resolution & Record Button & Actions -->
      <div class="flex items-center gap-2">
        <!-- Resolution Picker -->
        <select v-if="!vessel.isRecording" v-model="selectedRes"
          class="text-[10px] font-mono bg-slate-900/80 border border-white/20 text-white rounded px-1.5 py-1 focus:outline-none opacity-0 group-hover:opacity-100 transition-opacity">
          <option value="640x480">640x480 (SD)</option>
          <option value="1280x720">1280x720 (HD)</option>
          <option value="1920x1080">1920x1080 (FHD)</option>
        </select>

        <!-- Record Button -->
        <button @click="handleToggleRecord"
          :class="[
            'px-2.5 py-1 rounded flex items-center gap-1.5 text-[10px] font-bold tracking-wider transition-all shadow-md cursor-pointer',
            vessel.isRecording 
              ? 'bg-red-600 text-white hover:bg-red-700 animate-pulse border border-red-400' 
              : 'bg-slate-900/90 text-white border border-white/20 hover:bg-red-600 hover:text-white'
          ]"
          :title="vessel.isRecording ? 'Stop Recording Raw Stream' : 'Record Raw Stream (No Object Detection)'">
          <VideoOff v-if="vessel.isRecording" class="w-3.5 h-3.5" />
          <Video v-else class="w-3.5 h-3.5 text-red-500" />
          <span>{{ vessel.isRecording ? 'STOP REC' : 'REC MP4' }}</span>
        </button>

        <div class="flex gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button @click="handleRefresh" title="Reload stream"
            class="p-1.5 bg-card/80 rounded hover:bg-primary hover:text-slate-900 transition-all">
            <RefreshCw class="w-3.5 h-3.5" />
          </button>
          <button @click="handleFullscreen" :title="isFullscreen ? 'Exit fullscreen' : 'Fullscreen'"
            class="p-1.5 bg-card/80 rounded hover:bg-primary hover:text-slate-900 transition-all">
            <Minimize2 v-if="isFullscreen" class="w-3.5 h-3.5" />
            <Maximize2 v-else class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>

    <!-- Bottom Stats Overlay -->
    <div class="absolute bottom-3 left-3 text-[10px] font-mono text-(--text-secondary) opacity-80 bg-slate-950/70 px-2 py-1 rounded backdrop-blur border border-white/10">
      {{ status === 'CONNECTED' ? '640x480 @ 30FPS | MJPEG Stream' : 'OFFLINE' }}
      <span v-if="vessel.isRecording && vessel.recordingFilename" class="text-red-400 font-semibold ml-2">
        Saving: {{ vessel.recordingFilename.split('/').pop() }}
      </span>
    </div>
  </div>
</template>
