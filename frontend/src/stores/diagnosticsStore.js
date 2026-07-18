import { defineStore } from "pinia";
import { ref } from "vue";

export const useDiagnosticsStore = defineStore("diagnostics", () => {
  const sensorHealth = ref([
    { id: "gps", name: "GPS", status: "OK", value: "3D Fix" },
    { id: "imu", name: "IMU", status: "OK", value: "Stable" },
    { id: "telemetry", name: "Telemetry", status: "OK", value: "45ms" }
  ]);

  const errorLogs = ref([]);

  function addLog(severity, source, message) {
    errorLogs.value.unshift({
      timestamp: new Date().toLocaleTimeString(),
      severity,
      source,
      message
    });
  }

  return { sensorHealth, errorLogs, addLog };
});
