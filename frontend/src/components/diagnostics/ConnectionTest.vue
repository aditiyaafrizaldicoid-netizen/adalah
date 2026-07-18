<script setup>
import { Wifi, RefreshCw, Send } from 'lucide-vue-next';
import { ref } from 'vue';

const latency = ref(0);
const isTesting = ref(false);

const runTest = () => {
  isTesting.value = true;
  setTimeout(() => {
    latency.value = 42 + Math.floor(Math.random() * 10);
    isTesting.value = false;
  }, 1000);
};
</script>

<template>
  <div class="glass-card p-6 flex flex-col gap-6">
    <div class="flex items-center gap-3">
       <Wifi class="w-5 h-5 text-primary" />
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Connection Diagnostics</span>
    </div>

    <div class="grid grid-cols-2 gap-4">
       <div class="p-6 bg-(--bg-secondary) rounded-2xl border border-(--border-primary) text-center relative overflow-hidden">
          <span class="text-[10px] text-(--text-secondary) font-bold uppercase block mb-1">Latency (Ping)</span>
          <span class="text-3xl font-black text-(--text-primary) font-mono">{{ latency }}<span class="text-xs text-primary">ms</span></span>
          <div v-if="isTesting" class="absolute inset-0 bg-primary/10 flex items-center justify-center backdrop-blur-sm">
             <RefreshCw class="w-6 h-6 text-primary animate-spin" />
          </div>
       </div>
       <div class="p-6 bg-(--bg-secondary) rounded-2xl border border-(--border-primary) text-center">
          <span class="text-[10px] text-(--text-secondary) font-bold uppercase block mb-1">Data Throughput</span>
          <span class="text-3xl font-black text-(--text-primary) font-mono">2.4<span class="text-xs text-success">Mb/s</span></span>
       </div>
    </div>

    <div class="flex gap-2">
       <button @click="runTest" class="flex-1 py-3 bg-card hover:bg-(--bg-secondary) text-(--text-primary) rounded-xl text-[10px] font-bold uppercase transition-all flex items-center justify-center gap-2">
         <RefreshCw class="w-3.5 h-3.5" /> Start Link Test
       </button>
       <button class="flex-1 py-3 bg-primary text-slate-900 rounded-xl text-[10px] font-black uppercase transition-all flex items-center justify-center gap-2">
         <Send class="w-3.5 h-3.5" /> Force Sync
       </button>
    </div>
  </div>
</template>
