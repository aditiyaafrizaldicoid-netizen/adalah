<script setup>
import { MapPin, Satellite, Activity } from 'lucide-vue-next';

defineProps({
  lat: Number,
  lng: Number,
  fix: Number,
  satellites: Number
});

const fixTypes = ['NO FIX', '2D FIX', '3D FIX', 'DGPS', 'RTK'];
</script>

<template>
  <div class="glass-card p-5 space-y-4">
    <div class="flex justify-between items-center">
      <div class="flex items-center gap-2">
        <MapPin class="w-4 h-4 text-primary" />
        <span class="text-xs font-bold text-(--text-primary) uppercase tracking-widest">GPS Status</span>
      </div>
      <span :class="['text-[10px] font-black px-2 py-0.5 rounded', fix > 0 ? 'bg-success/20 text-success' : 'bg-danger/20 text-danger']">
        {{ fixTypes[fix] || 'UNKNOWN' }}
      </span>
    </div>
    
    <div class="grid grid-cols-2 gap-4">
      <div class="space-y-1">
        <span class="text-[10px] text-(--text-secondary) font-bold uppercase block">Latitude</span>
        <span class="text-xs font-mono text-(--text-primary)">{{ lat.toFixed(2) }}°</span>
      </div>
      <div class="space-y-1">
        <span class="text-[10px] text-(--text-secondary) font-bold uppercase block">Longitude</span>
        <span class="text-xs font-mono text-(--text-primary)">{{ lng.toFixed(2) }}°</span>
      </div>
    </div>

    <div class="flex items-center justify-between pt-3 border-t border-(--border-primary)">
      <div class="flex items-center gap-2">
        <Satellite class="w-3.5 h-3.5 text-(--text-secondary)" />
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-tighter">Sats: {{ satellites }}</span>
      </div>
      <div class="flex items-center gap-2">
        <Activity class="w-3.5 h-3.5 text-(--text-secondary)" />
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-tighter">HDOP: 0.8</span>
      </div>
    </div>
  </div>
</template>
