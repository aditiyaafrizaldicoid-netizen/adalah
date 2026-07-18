import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { useWebsocketStore } from "./websocketStore";

/**
 * Store untuk konfigurasi channel aktuator kapal ASV.
 * Sinkron dengan ChannelConfig di Python (flightcontrolAsv/config.py).
 *
 * Channel 1-8  = MAIN OUT (fisik di konektor MAIN Pixhawk)
 * Channel 9-16 = AUX OUT  (fisik di konektor AUX Pixhawk)
 */
export const useChannelConfigStore = defineStore("channelConfig", () => {
  const ws = useWebsocketStore();

  // --- State channel mapping ---
  const thrusterLeftCh = ref(1);   // MAIN 1 default
  const thrusterRightCh = ref(3);  // MAIN 3 default
  const servoLeftCh = ref(2);      // MAIN 2 default
  const servoRightCh = ref(4);     // MAIN 4 default
  const servoMethod = ref("rc_override"); // "rc_override" | "do_set_servo"

  // Apakah config sudah tersinkronisasi dengan ASV
  const isSynced = ref(false);
  const lastSyncTime = ref(null);

  // --- Computed helpers ---

  /** Label channel untuk ditampilkan di UI: "MAIN 1", "AUX 2", dll. */
  function channelLabel(ch) {
    if (ch <= 8) return `MAIN ${ch}`;
    return `AUX ${ch - 8}`;
  }

  const thrusterLeftLabel = computed(() => channelLabel(thrusterLeftCh.value));
  const thrusterRightLabel = computed(() => channelLabel(thrusterRightCh.value));
  const servoLeftLabel = computed(() => channelLabel(servoLeftCh.value));
  const servoRightLabel = computed(() => channelLabel(servoRightCh.value));

  /** Daftar semua opsi channel (1-16) dengan label MAIN/AUX */
  const channelOptions = computed(() => {
    const options = [];
    for (let i = 1; i <= 16; i++) {
      options.push({ value: i, label: channelLabel(i), group: i <= 8 ? "MAIN" : "AUX" });
    }
    return options;
  });

  // --- Actions ---

  /**
   * Kirim channel map yang sudah dikonfigurasi ke ASV via WebSocket.
   */
  function applyChannelMap() {
    ws.sendCommand({
      action: "set_channel_map",
      channel_map: {
        thruster_left_ch: thrusterLeftCh.value,
        thruster_right_ch: thrusterRightCh.value,
        servo_left_ch: servoLeftCh.value,
        servo_right_ch: servoRightCh.value,
        servo_method: servoMethod.value,
      },
    });
    console.log("[ChannelConfig] Sent set_channel_map to ASV");
  }

  /**
   * Minta ASV mengirim channel config saat ini (untuk sinkronisasi saat pertama konek).
   */
  function requestSync() {
    ws.sendCommand({ action: "get_channel_map" });
  }

  /**
   * Update state lokal dari payload CHANNEL_CONFIG yang diterima dari ASV.
   * Dipanggil oleh websocketStore saat menerima message type="CHANNEL_CONFIG".
   */
  function updateFromPayload(payload) {
    if (payload.thruster_left_ch !== undefined) thrusterLeftCh.value = payload.thruster_left_ch;
    if (payload.thruster_right_ch !== undefined) thrusterRightCh.value = payload.thruster_right_ch;
    if (payload.servo_left_ch !== undefined) servoLeftCh.value = payload.servo_left_ch;
    if (payload.servo_right_ch !== undefined) servoRightCh.value = payload.servo_right_ch;
    if (payload.servo_method !== undefined) servoMethod.value = payload.servo_method;
    isSynced.value = true;
    lastSyncTime.value = new Date().toLocaleTimeString();
    console.log("[ChannelConfig] Synced from ASV:", payload);
  }

  /**
   * Reset ke default (sama dengan default ChannelConfig di Python).
   */
  function resetToDefault() {
    thrusterLeftCh.value = 1;
    thrusterRightCh.value = 3;
    servoLeftCh.value = 2;
    servoRightCh.value = 4;
    servoMethod.value = "rc_override";
    isSynced.value = false;
  }

  return {
    // State
    thrusterLeftCh,
    thrusterRightCh,
    servoLeftCh,
    servoRightCh,
    servoMethod,
    isSynced,
    lastSyncTime,
    // Computed
    thrusterLeftLabel,
    thrusterRightLabel,
    servoLeftLabel,
    servoRightLabel,
    channelOptions,
    channelLabel,
    // Actions
    applyChannelMap,
    requestSync,
    updateFromPayload,
    resetToDefault,
  };
});
