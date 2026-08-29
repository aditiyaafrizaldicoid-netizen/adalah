<script setup>
import { computed } from 'vue';
import { useVesselStore } from '@/stores/vesselStore';
import { useWebsocketStore } from '@/stores/websocketStore';
import { useChannelConfigStore } from '@/stores/channelConfigStore';
import SensorHealthCard from "../components/diagnostics/SensorHealthCard.vue";
import ConnectionTest from "../components/diagnostics/ConnectionTest.vue";
import ErrorLogTable from "../components/diagnostics/ErrorLogTable.vue";
import SystemHealthOverview from "../components/diagnostics/SystemHealthOverview.vue";
import { Stethoscope, RefreshCw } from "lucide-vue-next";

const vessel = useVesselStore();
const ws = useWebsocketStore();
const cfg = useChannelConfigStore();

const sensors = computed(() => [
  {
    name: "GPS Module",
    status: vessel.isGpsValid ? "success" : "danger",
    value: vessel.isGpsValid ? `FIX (${vessel.satellites} Sats)` : "NO FIX",
    lastUpdate: vessel.isConnected ? "Live" : "Disconnected"
  },
  {
    name: "IMU / Compass",
    status: vessel.isConnected ? "success" : "danger",
    value: `${vessel.heading.toFixed(1)}° Heading`,
    lastUpdate: vessel.isConnected ? "Live" : "Offline"
  },
  {
    name: "Telemetry Link",
    status: ws.status === "CONNECTED" ? "success" : "danger",
    value: `${ws.latency || 0}ms Latency`,
    lastUpdate: ws.status
  },
  {
    name: "Battery System",
    status: vessel.batteryVolt > 11.5 ? "success" : "warning",
    value: `${vessel.batteryVolt.toFixed(1)}V (${vessel.batteryPct.toFixed(0)}%)`,
    lastUpdate: vessel.isConnected ? "Live" : "Offline"
  },
  {
    name: "Pixhawk FC",
    status: vessel.isConnected ? "success" : "danger",
    value: vessel.isConnected ? `ONLINE (${vessel.mode})` : "OFFLINE",
    lastUpdate: vessel.isConnected ? "Connected" : "No Heartbeat"
  },
  {
    name: "Video Camera Stream",
    status: vessel.cameraConnected ? "success" : "danger",
    value: vessel.cameraConnected ? "STREAMING" : "NO SIGNAL",
    lastUpdate: vessel.cameraConnected ? "Active" : "Disconnected"
  },
]);

// Gunakan vessel.warnings sebagai log — sudah berisi data real dari ASV
const errorLogs = computed(() =>
  vessel.warnings.map(w => ({
    timestamp: new Date(w.timestamp).toLocaleTimeString(),
    severity: w.level === 'critical' ? 'danger' : w.level === 'info' ? 'info' : 'warning',
    source: w.code,
    message: w.message,
  }))
);

function reScan() {
  if (ws.status !== 'CONNECTED') return;
  // Minta ASV kirim channel config dan mission status terbaru
  cfg.requestSync();
  ws.sendCommand({ action: 'get_mission_status' });
}
</script>

<template>
  <div class="p-3 sm:p-6 h-full overflow-y-auto space-y-4 sm:space-y-6">
    <div class="flex justify-between items-end">
      <div>
        <h1 class="text-2xl font-bold text-(--text-primary) tracking-tight flex items-center gap-3">
          <Stethoscope class="text-primary w-6 h-6" />
          SYSTEM DIAGNOSTICS
        </h1>
        <p class="text-(--text-secondary) text-xs mt-1 uppercase tracking-widest font-bold">Health Monitoring & Error Logging</p>
      </div>
      <button @click="reScan"
        :disabled="ws.status !== 'CONNECTED'"
        class="bg-card hover:bg-(--bg-secondary) text-(--text-primary) px-4 py-2 rounded-lg font-bold text-xs flex items-center gap-2 border border-(--border-subtle) transition-all disabled:opacity-40 disabled:cursor-not-allowed">
        <RefreshCw class="w-4 h-4" />
        RE-SCAN SYSTEM
      </button>
    </div>

    <!-- Sensor Health Grid -->
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
      <div class="col-span-12 lg:col-span-8 flex flex-col gap-6">
        <ErrorLogTable :logs="errorLogs" @clear="vessel.clearAllWarnings()" />
      </div>
      <div class="col-span-12 lg:col-span-4 flex flex-col gap-6">
        <ConnectionTest />
        <SystemHealthOverview />
      </div>
    </div>
  </div>
</template>
