<script setup>
import { MousePointer2, PlusCircle, Trash2, Save } from 'lucide-vue-next';

defineProps({
  waypoints: { type: Array, default: () => [] }
});

const emit = defineEmits(['add', 'delete', 'clear', 'upload']);
</script>

<template>
  <div class="glass-card p-4 flex flex-col gap-4 border-l-4 border-l-primary">
    <div class="flex items-center justify-between">
      <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Waypoint Editor</span>
      <div class="flex gap-2">
        <button @click="$emit('clear')" class="p-1.5 hover:bg-danger/20 text-danger rounded transition-all"><Trash2 class="w-3.5 h-3.5" /></button>
        <button @click="$emit('upload')" class="p-1.5 bg-primary/20 text-primary rounded hover:bg-primary hover:text-slate-900 transition-all"><Save class="w-3.5 h-3.5" /></button>
      </div>
    </div>
    
    <div class="space-y-2 max-h-48 overflow-y-auto pr-2">
      <div v-for="(wp, i) in waypoints" :key="i" class="p-2 bg-card/50 rounded border border-(--border-subtle) flex justify-between items-center group">
        <div>
          <span class="text-[10px] font-bold text-primary block">WP {{ (i+1).toString().padStart(2, '0') }}</span>
          <span class="text-[10px] font-mono text-(--text-secondary)">{{ wp.lat.toFixed(5) }}, {{ wp.lng.toFixed(5) }}</span>
        </div>
        <button @click="$emit('delete', i)" class="opacity-0 group-hover:opacity-100 transition-opacity text-danger"><Trash2 class="w-3 h-3" /></button>
      </div>
    </div>
    
    <div class="flex gap-2">
       <button class="flex-1 flex items-center justify-center gap-2 py-2 bg-card hover:bg-(--bg-secondary) rounded-lg text-[10px] font-bold uppercase transition-all">
         <MousePointer2 class="w-3 h-3" /> Select
       </button>
       <button class="flex-1 flex items-center justify-center gap-2 py-2 bg-primary text-slate-900 rounded-lg text-[10px] font-black uppercase transition-all">
         <PlusCircle class="w-3 h-3" /> Add WP
       </button>
    </div>
  </div>
</template>
