<script setup>
import { MapPin, Navigation, Camera, Anchor } from 'lucide-vue-next';

defineProps({
  waypoints: Array
});

const getIcon = (type) => {
  if (type === 'IMAGE') return Camera;
  if (type === 'DOCK') return Anchor;
  return Navigation;
};
</script>

<template>
  <div class="glass-card overflow-hidden">
    <table class="w-full text-left">
      <thead class="bg-(--bg-secondary) text-(--text-secondary) text-[10px] font-black uppercase tracking-widest">
        <tr>
          <th class="p-3">#</th>
          <th class="p-3">Type</th>
          <th class="p-3">Coords (X,Y)</th>
          <th class="p-3 text-right">Status</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-800/50 font-mono text-[10px]">
        <tr v-for="(wp, i) in waypoints" :key="i" class="hover:bg-card/30 transition-colors">
          <td class="p-3 text-(--text-secondary)">{{ (i+1).toString().padStart(2, '0') }}</td>
          <td class="p-3">
             <div class="flex items-center gap-2">
               <component :is="getIcon(wp.type)" class="w-3 h-3 text-primary" />
               <span class="text-(--text-primary)">{{ wp.type }}</span>
             </div>
          </td>
          <td class="p-3 text-(--text-secondary)">{{ wp.x.toFixed(1) }}, {{ wp.y.toFixed(1) }}</td>
          <td class="p-3 text-right">
             <span :class="['px-1.5 py-0.5 rounded-sm font-bold', wp.done ? 'bg-success/10 text-success' : 'bg-card text-(--text-muted)']">
               {{ wp.done ? 'DONE' : 'PENDING' }}
             </span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
