<script setup>
import { Database, Search } from "lucide-vue-next";
import SessionList from "../components/data/SessionList.vue";
import RunPlayback from "../components/data/RunPlayback.vue";
import ExportPanel from "../components/data/ExportPanel.vue";

const sessions = [
  { id: 1, date: "2026-05-11 14:20", duration: "12m 45s", nm: 20, score: 145.2, status: "SUCCESS" },
  { id: 2, date: "2026-05-11 10:15", duration: "08m 12s", nm: 12, score: 42.1, status: "ABORTED" },
  { id: 3, date: "2026-05-10 16:45", duration: "15m 30s", nm: 20, score: 128.5, status: "SUCCESS" },
];
</script>

<template>
  <div class="p-6 h-full overflow-y-auto space-y-6">
    <div class="flex justify-between items-end">
      <div>
        <h1 class="text-2xl font-bold text-(--text-primary) tracking-tight flex items-center gap-3">
          <Database class="text-primary w-6 h-6" />
          DATA MANAGER
        </h1>
        <p class="text-(--text-secondary) text-xs mt-1 uppercase tracking-widest font-bold">Session History & Analytics</p>
      </div>
      
      <div class="relative">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-(--text-secondary)" />
        <input type="text" placeholder="Search sessions..." class="bg-card border border-(--border-subtle) rounded-lg pl-10 pr-4 py-2 text-sm text-(--text-primary) focus:outline-none focus:border-primary transition-all w-64" />
      </div>
    </div>

    <div class="grid grid-cols-12 gap-6">
       <!-- Session Table (Sub-component) -->
       <div class="col-span-12 lg:col-span-8">
          <SessionList :sessions="sessions" />
       </div>

       <!-- Replay & Export (Sub-components) -->
       <div class="col-span-12 lg:col-span-4 flex flex-col gap-6">
          <RunPlayback />
          <ExportPanel />
       </div>
    </div>
  </div>
</template>
