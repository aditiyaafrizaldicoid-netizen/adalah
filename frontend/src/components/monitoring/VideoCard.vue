<script setup>
import { ref, computed } from 'vue';
import { RefreshCw, AlertCircle, Camera } from 'lucide-vue-next';
import { useMjpegStream } from '@/composables/useMjpegStream';

const props = defineProps({
    title: String,
    src: String,
    label: String,
    labelColor: { type: String, default: 'blue' },
    aspect: { type: String, default: 'aspect-video' },
    objectFit: { type: String, default: 'object-contain' }
});

const isMounted = ref(true);
const srcRef = computed(() => props.src);
const { activeSrc, isError, onError, onLoad, reload, imgRef, BLANK } = useMjpegStream(srcRef);
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
            <img ref="imgRef" :src="activeSrc" @error="onError" @load="onLoad" class="w-full h-full"
                :class="[objectFit, { 'opacity-0': isError || activeSrc === BLANK }]" />

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
            </div>
        </div>
    </div>
</template>