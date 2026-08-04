import { defineStore } from "pinia";
import { ref } from "vue";

export const useDiagnosticsStore = defineStore("diagnostics", () => {
  const sensorHealth = ref([]);


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
