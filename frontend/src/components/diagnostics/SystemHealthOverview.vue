<script setup>
import { Cpu, Database, Activity, Thermometer } from 'lucide-vue-next';
import ProgressBar from '../ui/ProgressBar.vue';
</script>

<template>
  <div class="glass-card p-6 space-y-6">
    <div class="flex items-center gap-2 mb-2">
       <Activity class="w-4 h-4 text-primary" />
       <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest">Hardware Resource Summary</span>
    </div>

    <div class="grid grid-cols-2 gap-6">
       <div class="space-y-3">
          <div class="flex justify-between text-[10px] font-bold uppercase">
             <span class="flex items-center gap-2 text-(--text-secondary)"><Cpu class="w-3 h-3" /> Processor</span>
             <span class="text-(--text-primary)">12%</span>
          </div>
          <ProgressBar :progress="12" color="primary" />
       </div>
       <div class="space-y-3">
          <div class="flex justify-between text-[10px] font-bold uppercase">
             <span class="flex items-center gap-2 text-(--text-secondary)"><Database class="w-3 h-3" /> Memory</span>
             <span class="text-(--text-primary)">2.4 GB</span>
          </div>
          <ProgressBar :progress="40" color="primary" />
       </div>
       <div class="space-y-3">
          <div class="flex justify-between text-[10px] font-bold uppercase">
             <span class="flex items-center gap-2 text-(--text-secondary)"><Activity class="w-3 h-3" /> Disk I/O</span>
             <span class="text-(--text-primary)">1.2 MB/s</span>
          </div>
          <ProgressBar :progress="15" color="success" />
       </div>
       <div class="space-y-3">
          <div class="flex justify-between text-[10px] font-bold uppercase">
             <span class="flex items-center gap-2 text-(--text-secondary)"><Thermometer class="w-3 h-3" /> Temp</span>
             <span class="text-warning">42°C</span>
          </div>
          <ProgressBar :progress="42" color="warning" />
       </div>
    </div>
  </div>
</template>
