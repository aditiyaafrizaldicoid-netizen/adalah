<script setup>
import { ref, onMounted } from 'vue';
import { Save, FolderOpen, Download, Trash2, Plus, RefreshCw } from 'lucide-vue-next';

import { API_BASE } from '@/config/api';

const profiles = ref([]);
const loading = ref(false);
const newProfileName = ref('');
const feedback = ref('');
const showForm = ref(false);

async function fetchProfiles() {
  loading.value = true;
  try {
    const res = await fetch(`${API_BASE}/api/v1/calibration/profiles`);
    const json = await res.json();
    profiles.value = json.data || [];
  } catch (e) {
    feedback.value = `Gagal load: ${e.message}`;
  } finally {
    loading.value = false;
  }
}

async function saveProfile() {
  if (!newProfileName.value.trim()) return;
  try {
    const res = await fetch(`${API_BASE}/api/v1/calibration/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: newProfileName.value.trim(), is_default: false })
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    newProfileName.value = '';
    showForm.value = false;
    feedback.value = 'Profil berhasil disimpan';
    setTimeout(() => { feedback.value = ''; }, 3000);
    await fetchProfiles();
  } catch (e) {
    feedback.value = `Gagal simpan: ${e.message}`;
  }
}

function downloadProfile(profile) {
  const blob = new Blob([JSON.stringify(profile, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `calib_${profile.name.replace(/\s+/g, '_')}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

async function importFromFile() {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.json';
  input.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const res = await fetch(`${API_BASE}/api/v1/calibration/profiles`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: data.name || file.name, ...data })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      feedback.value = 'Profil berhasil diimport';
      setTimeout(() => { feedback.value = ''; }, 3000);
      await fetchProfiles();
    } catch (e) {
      feedback.value = `Gagal import: ${e.message}`;
    }
  };
  input.click();
}

onMounted(fetchProfiles);
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex justify-between items-center">
      <h3 class="text-sm font-black text-(--text-primary) uppercase tracking-widest flex items-center gap-2">
        <FolderOpen class="w-4 h-4 text-primary" /> Calibration Profiles
      </h3>
      <button @click="fetchProfiles" :disabled="loading"
        class="p-2 rounded-lg text-(--text-secondary) hover:text-primary hover:bg-card transition-all">
        <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
      </button>
    </div>

    <!-- Profile Table -->
    <div class="glass-card overflow-hidden">
      <table class="w-full text-left">
        <thead class="bg-(--bg-secondary) text-(--text-secondary) text-[10px] font-black uppercase tracking-widest">
          <tr>
            <th class="p-4">Profile Name</th>
            <th class="p-4">Created</th>
            <th class="p-4 text-right">Actions</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-800/50 font-mono text-[10px]">
          <tr v-if="!profiles.length">
            <td colspan="3" class="p-8 text-center text-(--text-muted) italic">Belum ada profil tersimpan</td>
          </tr>
          <tr v-for="p in profiles" :key="p.id" class="hover:bg-card/30 transition-colors group">
            <td class="p-4 text-(--text-primary) font-bold">{{ p.name }}</td>
            <td class="p-4 text-(--text-secondary)">{{ p.created_at ? new Date(p.created_at).toLocaleDateString() : '—' }}</td>
            <td class="p-4 text-right">
              <div class="flex justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                <button @click="downloadProfile(p)" title="Download JSON"
                  class="p-1.5 hover:bg-primary/20 text-primary rounded transition-all">
                  <Download class="w-3.5 h-3.5" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- New Profile Form -->
    <div v-if="showForm" class="glass-card p-4 space-y-3">
      <label class="text-[10px] font-bold text-(--text-secondary) uppercase">Nama Profil Baru</label>
      <input v-model="newProfileName" placeholder="Contoh: Kompetisi Sesi 1" @keyup.enter="saveProfile"
        class="w-full bg-(--bg-secondary) border border-(--border-subtle) rounded-lg px-3 py-2 text-sm text-(--text-primary) font-mono focus:outline-none focus:border-primary" />
      <div class="flex gap-2">
        <button @click="showForm = false"
          class="flex-1 py-2 text-xs font-bold text-(--text-secondary) bg-card rounded-lg border border-(--border-subtle)">
          Batal
        </button>
        <button @click="saveProfile" :disabled="!newProfileName.trim()"
          class="flex-1 py-2 text-xs font-black text-slate-900 bg-primary rounded-lg disabled:opacity-40">
          Simpan
        </button>
      </div>
    </div>

    <!-- Feedback -->
    <div v-if="feedback" class="text-xs font-bold text-success flex items-center gap-2">
      {{ feedback }}
    </div>

    <!-- Action Buttons -->
    <div class="flex gap-4">
      <button @click="showForm = true"
        class="flex-1 bg-primary text-slate-900 py-3 rounded-xl font-black text-xs uppercase shadow-lg shadow-primary/20 hover:brightness-110 transition-all flex items-center justify-center gap-3">
        <Plus class="w-4 h-4" /> Simpan Profil Baru
      </button>
      <button @click="importFromFile"
        class="flex-1 bg-card text-(--text-primary) py-3 rounded-xl font-bold text-xs uppercase border border-(--border-subtle) hover:bg-(--bg-secondary) transition-all">
        Import dari File
      </button>
    </div>
  </div>
</template>
