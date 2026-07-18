<script setup>
import { ref, onMounted, onUnmounted, computed } from "vue";
import { 
  Battery, 
  Clock, 
  Zap,
  Radio,
  Sun,
  Moon
} from "lucide-vue-next";
import { useVesselStore } from '@/stores/vesselStore';
import { useThemeStore } from '@/stores/themeStore';
import { useWebsocketStore } from '@/stores/websocketStore';

const vessel = useVesselStore();
const themeStore = useThemeStore();
const wsStore = useWebsocketStore();

const currentTime = ref(new Date().toLocaleTimeString());
const isDark = computed(() => themeStore.theme === 'dark');

let timer;
onMounted(() => {
  timer = setInterval(() => {
    currentTime.value = new Date().toLocaleTimeString();
  }, 1000);
});

onUnmounted(() => {
  clearInterval(timer);
});
</script>

<template>
  <header class="h-16 bg-(--bg-topbar) border-b border-(--border-primary) flex items-center justify-between px-8 z-40 transition-colors duration-300">
    <div class="flex items-center gap-6">
      <div class="flex items-center gap-2">
        <div 
          :class="[
            'w-2 h-2 rounded-full animate-pulse',
            wsStore.status === 'CONNECTED' ? 'bg-success' : (wsStore.status === 'CONNECTING' ? 'bg-warning' : 'bg-danger')
          ]"
        ></div>
        <span class="text-xs font-bold uppercase tracking-widest text-(--text-secondary)">
          Vessel Status: 
          <span :class="wsStore.status === 'CONNECTED' ? 'text-success' : (wsStore.status === 'CONNECTING' ? 'text-warning' : 'text-danger')">
            {{ wsStore.status }}
          </span>
        </span>
      </div>
      
      <div class="h-4 w-px bg-(--border-primary)"></div>
      
      <div class="flex items-center gap-3 bg-(--bg-secondary) px-3 py-1.5 rounded-full border border-(--border-subtle)">
        <Radio class="w-4 h-4 text-primary" />
        <span class="text-xs font-mono text-(--text-primary)">ASV Backend WS</span>
      </div>
    </div>

    <div class="flex items-center gap-6">
      <!-- Theme Toggle -->
      <button @click="themeStore.toggleTheme()"
        class="p-2 rounded-lg transition-all duration-300 border border-(--border-primary)"
        :class="isDark
          ? 'bg-(--bg-card) text-(--accent-secondary)'
          : 'bg-(--bg-card) text-(--accent-primary)'">
        <Moon v-if="isDark" class="w-5 h-5" />
        <Sun v-else class="w-5 h-5" />
      </button>

      <!-- Simulation Toggle -->
      <div class="flex items-center gap-3 px-4 py-1.5 rounded-full bg-(--bg-secondary) border border-(--border-subtle) group cursor-pointer hover:border-primary/50 transition-colors" @click="vessel.toggleSimulation()">
        <div :class="['w-8 h-4 rounded-full relative transition-colors', vessel.isSimulating ? 'bg-primary' : 'bg-slate-700']">
          <div :class="['absolute top-1 w-2 h-2 rounded-full bg-white transition-all', vessel.isSimulating ? 'left-5' : 'left-1']"></div>
        </div>
        <span :class="['text-xs font-bold uppercase tracking-wider', vessel.isSimulating ? 'text-primary' : 'text-(--text-secondary)']">
          Simulation
        </span>
      </div>

      <div class="flex items-center gap-4 text-(--text-secondary)">
        <div class="flex items-center gap-2">
          <Battery class="w-5 h-5 text-success" />
          <span class="text-sm font-mono font-bold text-(--text-primary)">{{ vessel.batteryPct.toFixed(2) }}%</span>
        </div>
        <div class="flex items-center gap-2">
          <Clock class="w-5 h-5 text-primary" />
          <span class="text-sm font-mono font-bold text-(--text-primary)">{{ currentTime }}</span>
        </div>
      </div>
      
      <button class="bg-(--accent-primary) hover:bg-(--accent-primary-hover) text-white px-6 py-2 rounded-lg font-bold text-sm flex items-center gap-2 shadow-lg shadow-primary/20 transition-all active:scale-95">
        <Zap class="w-4 h-4 fill-current" />
        STOP
      </button>
    </div>
  </header>
</template>
