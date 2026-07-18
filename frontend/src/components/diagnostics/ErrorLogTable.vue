<script setup>
import { AlertCircle, FileText, Trash2 } from 'lucide-vue-next';

defineProps({
  logs: Array
});
</script>

<template>
  <div class="glass-card overflow-hidden">
    <div class="p-4 bg-card/30 border-b border-(--border-subtle) flex justify-between items-center">
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest flex items-center gap-2">
         <AlertCircle class="w-4 h-4 text-danger" /> System Error Logs
       </span>
       <div class="flex gap-4">
         <button class="text-[10px] font-bold text-(--text-secondary) hover:text-(--text-primary) uppercase flex items-center gap-2">
           <Trash2 class="w-3 h-3" /> Clear
         </button>
         <button class="text-[10px] font-bold text-primary hover:underline uppercase flex items-center gap-2">
           <FileText class="w-3 h-3" /> Export
         </button>
       </div>
    </div>
    <div class="max-h-96 overflow-y-auto">
      <table class="w-full text-left">
        <thead class="bg-(--bg-secondary) text-(--text-secondary) text-[10px] font-black uppercase tracking-widest sticky top-0 z-10">
          <tr>
            <th class="p-4">Timestamp</th>
            <th class="p-4">Level</th>
            <th class="p-4">Source</th>
            <th class="p-4">Description</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-800/50 font-mono text-[10px]">
          <tr v-for="(log, i) in logs" :key="i" class="hover:bg-card/30 transition-colors">
            <td class="p-4 text-(--text-secondary)">{{ log.time }}</td>
            <td class="p-4">
               <span :class="['px-2 py-0.5 rounded-sm font-black', log.severity === 'danger' ? 'bg-danger/20 text-danger' : 'bg-warning/20 text-warning']">
                 {{ log.severity.toUpperCase() }}
               </span>
            </td>
            <td class="p-4 text-(--text-primary) font-bold uppercase">{{ log.source }}</td>
            <td class="p-4 text-(--text-secondary)">{{ log.message }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
