<script setup>
import { useDiagnosticsStore } from '@/stores/diagnosticsStore';
import SensorHealthCard from "../components/diagnostics/SensorHealthCard.vue";
import ConnectionTest from "../components/diagnostics/ConnectionTest.vue";
import ErrorLogTable from "../components/diagnostics/ErrorLogTable.vue";
import SystemHealthOverview from "../components/diagnostics/SystemHealthOverview.vue";
import { Stethoscope, RefreshCw } from "lucide-vue-next";

const diag = useDiagnosticsStore();

const sensors = [
  { name: "GPS Module", status: "success", value: "3D FIX (12 Sats)", lastUpdate: "0.2s ago" },
  { name: "IMU / Compass", status: "success", value: "STABLE", lastUpdate: "0.1s ago" },
  { name: "Telemetry Link", status: "success", value: "42ms Latency", lastUpdate: "0.5s ago" },
  { name: "Battery BMS", status: "warning", value: "11.2V (Low)", lastUpdate: "1.2s ago" },
  { name: "Motor Controller L", status: "success", value: "IDLE (32°C)", lastUpdate: "0.4s ago" },
  { name: "Motor Controller R", status: "success", value: "IDLE (34°C)", lastUpdate: "0.4s ago" },
  { name: "Surface Camera", status: "success", value: "STREAMING", lastUpdate: "0.1s ago" },
  { name: "Underwater Camera", status: "danger", value: "NO SIGNAL", lastUpdate: "5.4s ago" },
];
</script>

<template>
  <div class="p-6 h-full overflow-y-auto space-y-6">
    <div class="flex justify-between items-end">
      <div>
        <h1 class="text-2xl font-bold text-(--text-primary) tracking-tight flex items-center gap-3">
          <Stethoscope class="text-primary w-6 h-6" />
          SYSTEM DIAGNOSTICS
        </h1>
        <p class="text-(--text-secondary) text-xs mt-1 uppercase tracking-widest font-bold">Health Monitoring & Error Logging</p>
      </div>
      <button class="bg-card hover:bg-(--bg-secondary) text-(--text-primary) px-4 py-2 rounded-lg font-bold text-xs flex items-center gap-2 border border-(--border-subtle) transition-all">
        <RefreshCw class="w-4 h-4" />
        RE-SCAN SYSTEM
      </button>
    </div>

    <!-- Sensor Health Grid (Sub-components) -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
      <SensorHealthCard 
        v-for="s in sensors" 
        :key="s.name" 
        :name="s.name" 
        :status="s.status" 
        :value="s.value" 
        :lastUpdate="s.lastUpdate" 
      />
    </div>

    <div class="grid grid-cols-12 gap-6">
       <!-- Logs & Tests (Sub-components) -->
       <div class="col-span-12 lg:col-span-8 flex flex-col gap-6">
          <ErrorLogTable :logs="diag.errorLogs" />
       </div>

       <div class="col-span-12 lg:col-span-4 flex flex-col gap-6">
          <ConnectionTest />
          <SystemHealthOverview />
       </div>
    </div>
  </div>
</template>
