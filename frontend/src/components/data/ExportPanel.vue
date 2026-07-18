<script setup>
import { Download, FileSpreadsheet, FileText, FileJson, CheckSquare } from 'lucide-vue-next';
import { ref } from 'vue';

const selectedFormats = ref(['csv', 'pdf']);
const options = [
  { id: 'csv', name: 'Excel / CSV', icon: FileSpreadsheet, color: 'text-success' },
  { id: 'pdf', name: 'PDF Report', icon: FileText, color: 'text-danger' },
  { id: 'json', name: 'JSON Raw', icon: FileJson, color: 'text-warning' },
];
</script>

<template>
  <div class="glass-card p-6 space-y-6">
    <div class="flex items-center gap-3">
       <Download class="w-5 h-5 text-primary" />
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Export Dataset</span>
    </div>

    <div class="space-y-3">
       <div 
         v-for="opt in options" 
         :key="opt.id"
         @click="selectedFormats.includes(opt.id) ? selectedFormats = selectedFormats.filter(f => f !== opt.id) : selectedFormats.push(opt.id)"
         :class="['flex items-center justify-between p-4 bg-card/50 rounded-xl border cursor-pointer transition-all', selectedFormats.includes(opt.id) ? 'border-primary/50 bg-primary/5' : 'border-(--border-subtle)']"
       >
          <div class="flex items-center gap-4">
             <component :is="opt.icon" :class="['w-6 h-6', opt.color]" />
             <span class="text-xs font-bold text-(--text-primary) uppercase tracking-wider">{{ opt.name }}</span>
          </div>
          <div :class="['w-5 h-5 rounded border-2 flex items-center justify-center', selectedFormats.includes(opt.id) ? 'bg-primary border-primary text-slate-900' : 'border-(--border-subtle)']">
             <CheckSquare v-if="selectedFormats.includes(opt.id)" class="w-3.5 h-3.5" />
          </div>
       </div>
    </div>

    <button class="btn-primary w-full py-4 text-xs font-black uppercase flex items-center justify-center gap-3 shadow-xl shadow-primary/20">
       <Download class="w-4 h-4" /> Start Export Sequence
    </button>
  </div>
</template>
