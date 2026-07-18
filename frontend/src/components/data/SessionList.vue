<script setup>
import { Calendar, Play, Trash2, Download } from 'lucide-vue-next';

defineProps({
  sessions: Array
});
</script>

<template>
  <div class="glass-card overflow-hidden">
    <table class="w-full text-left">
      <thead class="bg-(--bg-secondary) text-(--text-secondary) text-[10px] font-black uppercase tracking-widest">
        <tr>
          <th class="p-4">Session Date</th>
          <th class="p-4">Duration</th>
          <th class="p-4">NM</th>
          <th class="p-4">Score</th>
          <th class="p-4 text-right">Actions</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-800/50 font-mono text-[10px]">
        <tr v-for="s in sessions" :key="s.id" class="hover:bg-card/30 transition-colors group">
          <td class="p-4">
             <div class="flex items-center gap-3">
                <Calendar class="w-4 h-4 text-(--text-muted)" />
                <span class="text-(--text-primary) font-bold">{{ s.date }}</span>
             </div>
          </td>
          <td class="p-4 text-(--text-secondary)">{{ s.duration }}</td>
          <td class="p-4 text-primary font-black">{{ s.nm }}/20</td>
          <td class="p-4 text-(--text-primary) font-black">{{ s.score.toFixed(1) }}</td>
          <td class="p-4 text-right">
             <div class="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button class="p-2 hover:bg-primary/20 text-primary rounded-lg transition-all"><Play class="w-3.5 h-3.5 fill-current" /></button>
                <button class="p-2 hover:bg-(--bg-secondary) text-(--text-secondary) rounded-lg transition-all"><Download class="w-3.5 h-3.5" /></button>
                <button class="p-2 hover:bg-danger/20 text-danger rounded-lg transition-all"><Trash2 class="w-3.5 h-3.5" /></button>
             </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
