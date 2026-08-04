<script setup>
import { computed } from 'vue';
import { Cpu, Database, Activity, Thermometer } from 'lucide-vue-next';
import ProgressBar from '../ui/ProgressBar.vue';
import { useVesselStore } from '@/stores/vesselStore';
import { useWebsocketStore } from '@/stores/websocketStore';

const vessel = useVesselStore();
const ws = useWebsocketStore();

const linkQuality = computed(() => ws.status === 'CONNECTED' ? 100 : 0);
const batteryProgress = computed(() => Math.min(100, Math.max(0, vessel.batteryPct)));
</script>

<template>
  <div class="glass-card p-6 space-y-6">
    <div class="flex items-center gap-2 mb-2">
       <Activity class="w-4 h-4 text-primary" />
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Hardware Resource Summary</span>
    </div>

    <div class="grid grid-cols-2 gap-6">
       <div class="space-y-3">
          <div class="flex justify-between text-[10px] font-bold uppercase">
             <span class="flex items-center gap-2 text-(--text-secondary)"><Cpu class="w-3 h-3" /> Link Quality</span>
             <span class="text-(--text-primary)">{{ linkQuality }}%</span>
          </div>
          <ProgressBar :progress="linkQuality" color="primary" />
       </div>
       <div class="space-y-3">
          <div class="flex justify-between text-[10px] font-bold uppercase">
             <span class="flex items-center gap-2 text-(--text-secondary)"><Database class="w-3 h-3" /> Battery Level</span>
             <span class="text-(--text-primary)">{{ vessel.batteryPct.toFixed(0) }}%</span>
          </div>
          <ProgressBar :progress="batteryProgress" color="primary" />
       </div>
       <div class="space-y-3">
          <div class="flex justify-between text-[10px] font-bold uppercase">
             <span class="flex items-center gap-2 text-(--text-secondary)"><Activity class="w-3 h-3" /> Satellites</span>
             <span class="text-(--text-primary)">{{ vessel.satellites }} Sats</span>
          </div>
          <ProgressBar :progress="Math.min(100, vessel.satellites * 5)" color="success" />
       </div>
       <div class="space-y-3">
          <div class="flex justify-between text-[10px] font-bold uppercase">
             <span class="flex items-center gap-2 text-(--text-secondary)"><Thermometer class="w-3 h-3" /> Voltage</span>
             <span class="text-warning">{{ vessel.batteryVolt.toFixed(1) }}V</span>
          </div>
          <ProgressBar :progress="Math.min(100, (vessel.batteryVolt / 16.8) * 100)" color="warning" />
       </div>
    </div>
  </div>
</template>

