<script setup>
import { ref, watch, onMounted } from "vue";
import { Database, Search, RefreshCw } from "lucide-vue-next";
import SessionList from "../components/data/SessionList.vue";
import RunPlayback from "../components/data/RunPlayback.vue";
import ExportPanel from "../components/data/ExportPanel.vue";

import { API_BASE } from "@/config/api";

const sessions = ref([]);
const loading = ref(false);
const error = ref('');
const searchQuery = ref('');

async function fetchSessions() {
  loading.value = true;
  error.value = '';
  try {
    const res = await fetch(`${API_BASE}/api/v1/sessions`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    sessions.value = json.data ?? [];
  } catch (e) {
    error.value = `Gagal memuat sesi: ${e.message}`;
    sessions.value = [];
  } finally {
    loading.value = false;
  }
}

async function handleDownload(filename) {
  const url = `${API_BASE}/api/v1/sessions/${encodeURIComponent(filename)}`;
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
}

async function handleDelete(filename) {
  if (!confirm(`Hapus sesi "${filename}"?`)) return;
  try {
    const res = await fetch(`${API_BASE}/api/v1/sessions/${encodeURIComponent(filename)}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    sessions.value = sessions.value.filter(s => s.filename !== filename);
  } catch (e) {
    alert(`Gagal hapus: ${e.message}`);
  }
}

const filteredSessions = ref([]);

function applySearch() {
  const q = searchQuery.value.toLowerCase();
  filteredSessions.value = q
    ? sessions.value.filter(s => s.filename.toLowerCase().includes(q) || s.date.includes(q))
    : sessions.value;
}

// Reactive filter when sessions or search changes
watch([sessions, searchQuery], applySearch, { immediate: true });

onMounted(fetchSessions);
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

      <div class="flex items-center gap-3">
        <button @click="fetchSessions" :disabled="loading"
          class="p-2 rounded-lg bg-card border border-(--border-subtle) hover:border-primary text-(--text-secondary) hover:text-primary transition-all disabled:opacity-40">
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': loading }" />
        </button>
        <div class="relative">
          <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-(--text-secondary)" />
          <input v-model="searchQuery" type="text" placeholder="Search sessions..."
            class="bg-card border border-(--border-subtle) rounded-lg pl-10 pr-4 py-2 text-sm text-(--text-primary) focus:outline-none focus:border-primary transition-all w-64" />
        </div>
      </div>
    </div>

    <!-- Error banner -->
    <div v-if="error" class="text-xs text-danger bg-danger/10 border border-danger/30 rounded-lg px-4 py-2">
      {{ error }}
    </div>

    <!-- Loading state -->
    <div v-if="loading && !sessions.length" class="text-xs text-(--text-muted) italic">Memuat sesi...</div>

    <div class="grid grid-cols-12 gap-6">
       <!-- Session Table (Sub-component) -->
       <div class="col-span-12 lg:col-span-8">
          <SessionList
            :sessions="filteredSessions"
            @download="handleDownload"
            @delete="handleDelete"
          />
       </div>

       <!-- Replay & Export (Sub-components) -->
       <div class="col-span-12 lg:col-span-4 flex flex-col gap-6">
          <RunPlayback />
          <ExportPanel />
       </div>
    </div>
  </div>
</template>
