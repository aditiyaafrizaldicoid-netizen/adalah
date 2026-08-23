<script setup>
import { ref, computed } from 'vue';
import { RefreshCw, AlertCircle, Camera, Video, VideoOff, CircleDot, Wifi, WifiOff } from 'lucide-vue-next';
import { useMjpegStream } from '@/composables/useMjpegStream';
import { useVesselStore } from '@/stores/vesselStore';
import { useWebsocketStore } from '@/stores/websocketStore';

const props = defineProps({
    title: String,
    src: String,
    label: String,
    labelColor: { type: String, default: 'blue' },
    aspect: { type: String, default: 'aspect-video' },
    objectFit: { type: String, default: 'object-cover' }
});

const vessel = useVesselStore();
const wsStore = useWebsocketStore();
const selectedRes = ref('640x480');

const isMounted = ref(true);
const srcRef = computed(() => props.src);
const { activeSrc, isError, onError, onLoad, reload, imgRef, BLANK } = useMjpegStream(srcRef);

const handleToggleRecord = () => {
    const [w, h] = selectedRes.value.split('x');
    wsStore.toggleRecording(parseInt(w), parseInt(h));
};

const handleToggleStreaming = () => {
    wsStore.toggleStreaming();
};
</script>

<template>
    <div class="panel h-full flex flex-col group/video overflow-hidden">
        <!-- Premium Header -->
        <div :class="[
            'panel-header justify-between',
            labelColor === 'blue' ? 'panel-header-blue' :
                labelColor === 'green' ? 'panel-header-green' :
                    labelColor === 'orange' ? 'panel-header-orange' :
                        labelColor === 'purple' ? 'panel-header-purple' : 'panel-header-teal'
        ]">
            <h3 class="flex items-center gap-2">
                <Camera class="w-4 h-4" />
                {{ title || 'VIDEO STREAM' }}
            </h3>
            <div class="flex items-center gap-3">
                <!-- Badge: Streaming OFF -->
                <span v-if="!vessel.isStreaming"
                    class="flex items-center gap-1.5 bg-slate-700/90 text-slate-300 text-[10px] px-2 py-0.5 rounded font-black tracking-widest border border-slate-500">
                    <WifiOff class="w-3 h-3" />
                    STREAM OFF
                </span>
                <!-- Badge: Recording -->
                <span v-if="vessel.isRecording"
                    class="flex items-center gap-1.5 bg-red-600/90 text-white text-[10px] px-2 py-0.5 rounded font-black tracking-widest animate-pulse border border-red-400">
                    <CircleDot class="w-3 h-3 text-white" />
                    REC {{ vessel.recordingResolution }}
                </span>
                <span class="flex items-center gap-1.5" v-if="isMounted && !isError">
                    <span class="led-green"></span>
                    <span class="text-[10px] font-black text-white opacity-80 uppercase tracking-widest">LIVE</span>
                </span>
                <button @click="reload" class="p-1 hover:text-white transition-colors" title="Reconnect Stream">
                    <RefreshCw class="w-3.5 h-3.5 group-hover/video:rotate-180 transition-transform duration-700" />
                </button>
            </div>
        </div>

        <!-- Video Viewport -->
        <div
            :class="['relative bg-black flex items-center justify-center overflow-hidden flex-1 group-hover/video:shadow-[inset_0_0_40px_rgba(0,0,0,0.8)] transition-all', aspect]">
            <img ref="imgRef" :src="activeSrc" @error="onError" @load="onLoad" class="w-full h-full  object-contain"
                :class="[objectFit, { 'opacity-0': isError || activeSrc === BLANK }]" />

            <!-- Record & Streaming Overlay Controls (Top Right overlay inside video) -->
            <div class="absolute top-3 right-3 z-10 flex items-center gap-2">
                <select v-if="!vessel.isRecording" v-model="selectedRes"
                    class="text-[10px] font-mono bg-black/80 border border-white/20 text-white rounded px-1.5 py-1 focus:outline-none opacity-0 group-hover/video:opacity-100 transition-opacity">
                    <option value="640x480">640x480 (SD)</option>
                    <option value="1280x720">1280x720 (HD)</option>
                    <option value="1920x1080">1920x1080 (FHD)</option>
                </select>

                <!-- Tombol Toggle Streaming -->
                <button @click="handleToggleStreaming"
                    :class="[
                        'px-2.5 py-1 rounded flex items-center gap-1.5 text-[10px] font-bold tracking-wider transition-all shadow-lg cursor-pointer opacity-0 group-hover/video:opacity-100',
                        vessel.isStreaming
                            ? 'bg-black/80 text-white border border-white/20 hover:bg-slate-600 hover:text-white'
                            : 'bg-slate-700 text-slate-200 border border-slate-400 hover:bg-green-600 hover:text-white'
                    ]"
                    :title="vessel.isStreaming ? 'Matikan Streaming (hemat CPU/bandwidth, YOLO tetap aktif)' : 'Aktifkan Streaming ke Base Station'">
                    <WifiOff v-if="vessel.isStreaming" class="w-3.5 h-3.5 text-slate-300" />
                    <Wifi v-else class="w-3.5 h-3.5 text-green-400" />
                    <span>{{ vessel.isStreaming ? 'STOP STREAM' : 'START STREAM' }}</span>
                </button>

                <!-- Tombol Toggle Recording -->
                <button @click="handleToggleRecord"
                    :class="[
                        'px-2.5 py-1 rounded flex items-center gap-1.5 text-[10px] font-bold tracking-wider transition-all shadow-lg cursor-pointer',
                        vessel.isRecording 
                            ? 'bg-red-600 text-white hover:bg-red-700 animate-pulse border border-red-400' 
                            : 'bg-black/80 text-white border border-white/20 hover:bg-red-600 hover:text-white'
                    ]"
                    :title="vessel.isRecording ? 'Stop Recording Raw Stream' : 'Record Raw Stream (No Object Detection)'">
                    <VideoOff v-if="vessel.isRecording" class="w-3.5 h-3.5" />
                    <Video v-else class="w-3.5 h-3.5 text-red-500" />
                    <span>{{ vessel.isRecording ? 'STOP REC' : 'REC MP4' }}</span>
                </button>
            </div>

            <!-- Loading / Error Overlay -->
            <div v-if="isError || activeSrc === BLANK"
                class="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-background/20 backdrop-blur-sm transition-all duration-500">
                <div
                    class="w-12 h-12 rounded-full bg-muted border border-border flex items-center justify-center shadow-2xl">
                    <AlertCircle v-if="isError" class="w-6 h-6 text-danger animate-pulse" />
                    <RefreshCw v-else class="w-6 h-6 text-primary animate-spin" />
                </div>
                <div class="text-center">
                    <p class="text-[10px] font-black uppercase tracking-[0.2em] text-white/50">
                        {{ isError ? 'Signal Interrupted' : 'Initializing Stream...' }}
                    </p>
                    <button v-if="isError" @click="reload"
                        class="mt-2 text-[10px] font-bold text-primary hover:underline uppercase tracking-widest">
                        Try Reconnect
                    </button>
                </div>
            </div>

            <!-- Corner Metadata Overlay (Aesthetic) -->
            <div
                class="absolute bottom-4 left-4 flex gap-2 opacity-0 group-hover/video:opacity-100 transition-opacity duration-300">
                <div
                    class="px-2 py-1 bg-black/60 backdrop-blur-md border border-white/10 rounded text-[8px] font-mono text-white/70 uppercase">
                    640x480
                </div>
                <div
                    class="px-2 py-1 bg-black/60 backdrop-blur-md border border-white/10 rounded text-[8px] font-mono text-white/70 uppercase">
                    MJPEG
                </div>
                <div v-if="vessel.isRecording && vessel.recordingFilename"
                    class="px-2 py-1 bg-red-950/80 border border-red-500/30 rounded text-[8px] font-mono text-red-300 uppercase">
                    Saving MP4: {{ vessel.recordingFilename.split('/').pop() }}
                </div>
            </div>
        </div>
    </div>
</template>