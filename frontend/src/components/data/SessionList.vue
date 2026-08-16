<script setup>
import { Calendar, Download, Trash2, FileText } from 'lucide-vue-next';

defineProps({
  sessions: Array
});

const emit = defineEmits(['download', 'delete']);
</script>

<template>
  <div class="glass-card overflow-hidden">
    <table class="w-full text-left">
      <thead class="bg-(--bg-secondary) text-(--text-secondary) text-[10px] font-black uppercase tracking-widest">
        <tr>
          <th class="p-4">Session Date</th>
          <th class="p-4">File</th>
          <th class="p-4">Records</th>
          <th class="p-4">Size</th>
          <th class="p-4 text-right">Actions</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-800/50 font-mono text-[10px]">
        <tr v-if="!sessions || !sessions.length">
          <td colspan="5" class="p-8 text-center text-(--text-muted) italic text-[11px]">
            Belum ada sesi log tersimpan
          </td>
        </tr>
        <tr v-for="s in sessions" :key="s.filename" class="hover:bg-card/30 transition-colors group">
          <td class="p-4">
            <div class="flex items-center gap-3">
              <Calendar class="w-4 h-4 text-(--text-muted) shrink-0" />
              <span class="text-(--text-primary) font-bold">{{ s.date }}</span>
            </div>
          </td>
          <td class="p-4">
            <div class="flex items-center gap-2 text-(--text-secondary)">
              <FileText class="w-3.5 h-3.5 text-primary shrink-0" />
              <span class="truncate max-w-[160px]" :title="s.filename">{{ s.filename }}</span>
            </div>
          </td>
          <td class="p-4 text-primary font-black">{{ s.records.toLocaleString() }}</td>
          <td class="p-4 text-(--text-secondary)">{{ s.size_kb }} KB</td>
          <td class="p-4 text-right">
            <div class="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <button @click="emit('download', s.filename)"
                class="p-2 hover:bg-(--bg-secondary) text-(--text-secondary) hover:text-primary rounded-lg transition-all"
                title="Download CSV">
                <Download class="w-3.5 h-3.5" />
              </button>
              <button @click="emit('delete', s.filename)"
                class="p-2 hover:bg-danger/20 text-danger rounded-lg transition-all"
                title="Hapus sesi">
                <Trash2 class="w-3.5 h-3.5" />
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
