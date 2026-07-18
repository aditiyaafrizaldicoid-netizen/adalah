<script setup>
import { Save, FolderOpen, Download, FileJson } from 'lucide-vue-next';

const profiles = [
  { name: 'Competition Day 1', date: '2026-05-11 08:00', author: 'EngTeam' },
  { name: 'Testing Pool Jakarta', date: '2026-04-20 14:30', author: 'EngTeam' },
  { name: 'Factory Reset', date: '2026-01-01 00:00', author: 'System' },
];
</script>

<template>
  <div class="space-y-6">
    <div class="glass-card overflow-hidden">
       <div class="p-4 bg-card/30 border-b border-(--border-subtle) flex justify-between items-center">
          <span class="text-xs font-bold text-(--text-primary) uppercase tracking-widest flex items-center gap-2">
            <FolderOpen class="w-4 h-4 text-primary" /> Saved Profiles
          </span>
       </div>
       <table class="w-full text-left">
          <thead class="bg-(--bg-secondary) text-(--text-secondary) text-[10px] font-black uppercase tracking-widest">
             <tr>
                <th class="p-4">Profile Name</th>
                <th class="p-4">Last Modified</th>
                <th class="p-4">Author</th>
                <th class="p-4 text-right">Actions</th>
             </tr>
          </thead>
          <tbody class="divide-y divide-slate-800/50 font-mono text-[10px]">
             <tr v-for="p in profiles" :key="p.name" class="hover:bg-card/30 transition-colors">
                <td class="p-4 text-(--text-primary) font-bold">{{ p.name }}</td>
                <td class="p-4 text-(--text-secondary)">{{ p.date }}</td>
                <td class="p-4 text-(--text-secondary) uppercase">{{ p.author }}</td>
                <td class="p-4 text-right">
                   <div class="flex justify-end gap-2">
                      <button class="p-1.5 hover:bg-primary/20 text-primary rounded transition-all"><Download class="w-3.5 h-3.5" /></button>
                      <button class="p-1.5 hover:bg-(--bg-secondary) text-(--text-secondary) rounded transition-all"><FileJson class="w-3.5 h-3.5" /></button>
                   </div>
                </td>
             </tr>
          </tbody>
       </table>
    </div>

    <div class="flex gap-4">
       <button class="flex-1 bg-primary text-slate-900 py-3 rounded-xl font-black text-xs uppercase shadow-lg shadow-primary/20 hover:bg-sky-400 transition-all flex items-center justify-center gap-3">
          <Save class="w-4 h-4" /> Save New Profile
       </button>
       <button class="flex-1 bg-card text-(--text-primary) py-3 rounded-xl font-bold text-xs uppercase border border-(--border-subtle) hover:bg-(--bg-secondary) transition-all">
          Import from File
       </button>
    </div>
  </div>
</template>
