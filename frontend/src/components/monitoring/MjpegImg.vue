<script setup>
import { computed } from 'vue';
import { useMjpegStream } from '@/composables/useMjpegStream';

const props = defineProps({
    src: { type: String, default: null },
    placeholder: { type: String, default: 'No Signal' },
});

const srcRef = computed(() => props.src);
const { activeSrc, isError, onError, onLoad, imgRef, BLANK } = useMjpegStream(srcRef);
</script>

<template>
    <!-- Placeholder when no src -->
    <slot v-if="!src" name="placeholder">
        <div class="w-full h-full flex items-center justify-center">
            <span class="text-[9px] font-black text-muted-foreground uppercase tracking-widest opacity-40">
                {{ placeholder }}
            </span>
        </div>
    </slot>

    <!-- MJPEG stream -->
    <div v-else class="relative w-full h-full">
        <img ref="imgRef" :src="activeSrc" @error="onError" @load="onLoad" class="w-full h-full object-contain"
            :class="{ 'opacity-0': isError || activeSrc === BLANK }" />
        <!-- Reconnecting spinner -->
        <div v-if="isError || activeSrc === BLANK"
            class="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/60">
            <div class="w-4 h-4 border-2 border-primary/40 border-t-primary rounded-full animate-spin"></div>
            <span class="text-[8px] font-black text-muted-foreground uppercase tracking-widest opacity-50">
                {{ isError ? 'Reconnecting...' : 'Connecting...' }}
            </span>
        </div>
    </div>
</template>