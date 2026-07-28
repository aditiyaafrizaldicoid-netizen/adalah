import { defineStore } from "pinia";
import { ref, computed } from "vue";

export const useVesselStore = defineStore("vessel", () => {
  // Telemetry State
  const lat = ref(-7.9215169);
  const lng = ref(112.5973649);
  const heading = ref(0);
  const sog = ref(0); // Speed Over Ground (knots)
  const cog = ref(0); // Course Over Ground

  const pitch = ref(0);
  const roll = ref(0);
  const yaw = ref(0);

  const batteryPct = ref(100);
  const batteryVolt = ref(12.6);

  const gpsFix = ref(0); // 0: No Fix, 1: 2D, 2: 3D, 3: DGPS, 4: RTK
  const satellites = ref(0);
  const signalStrength = ref(0);

  // Flight Controller Status (dari Pixhawk via MAVLink)
  const isConnected = ref(false);  // Pixhawk terdeteksi & heartbeat aktif
  const isArmed = ref(false);      // Motor sudah ARM
  const mode = ref('UNKNOWN');     // Mode aktif: MANUAL, GUIDED, AUTO, dll

  // Video Recording State (Tanpa Object Detection)
  const isRecording = ref(false);
  const recordingFilename = ref('');
  const recordingResolution = ref('640x480');

  // Camera & Connectivity State
  const cameraConnected = ref(false);  // Apakah stream kamera aktif
  const asvConnected = ref(false);     // Apakah Mini PC (ASV) terkoneksi ke base station

  // System Warnings (dari backend atau deteksi lokal)
  // Format: { id, level, code, message, timestamp }
  const warnings = ref([]);

  // Simulation State
  const isSimulating = ref(false);
  let simInterval = null;

  // Advanced Navigation Data
  const xte = ref(0);
  const dtw = ref(150.5);
  const nextWp = ref(1);

  // Engine Stats
  const thrusterL = ref(0);
  const thrusterR = ref(0);
  const rpmL = ref(0);
  const rpmR = ref(0);

  // Computed Properties
  const isGpsValid = computed(() => gpsFix.value >= 2);
  const batteryColor = computed(() => {
    if (batteryPct.value > 50) return "text-success";
    if (batteryPct.value > 20) return "text-warning";
    return "text-danger";
  });

  // Actions to update telemetry
  function updateTelemetry(data) {
    if (!isSimulating.value) {
      if (data.lat !== undefined && data.lat !== 0) lat.value = data.lat;
      if (data.lng !== undefined && data.lng !== 0) lng.value = data.lng;
    }

    // Always update these from real sensors even if simulating location
    if (data.heading !== undefined) {
      heading.value = data.heading;
      if (heading.value > 180) {
        heading.value -= 360;
      } else if (heading.value < -180) {
        heading.value += 360;
      }
    }
    if (data.sog !== undefined) sog.value = data.sog;
    if (data.cog !== undefined) cog.value = data.cog;
    if (data.pitch !== undefined) pitch.value = data.pitch;
    if (data.roll !== undefined) roll.value = data.roll;
    if (data.yaw !== undefined) yaw.value = data.yaw;
    if (data.battery_pct !== undefined) batteryPct.value = data.battery_pct;
    if (data.battery_volt !== undefined) batteryVolt.value = data.battery_volt;
    if (data.gps_fix !== undefined) gpsFix.value = data.gps_fix;
    if (data.satellites !== undefined) satellites.value = data.satellites;
    if (data.signal_strength !== undefined) signalStrength.value = data.signal_strength;
    // Status Pixhawk
    if (data.is_connected !== undefined) isConnected.value = data.is_connected;
    if (data.is_armed !== undefined) isArmed.value = data.is_armed;
    if (data.mode !== undefined) mode.value = data.mode;
    // Status Recording Video Mentah
    if (data.is_recording !== undefined) isRecording.value = data.is_recording;
    if (data.recording_filename !== undefined) recordingFilename.value = data.recording_filename;
    if (data.recording_resolution !== undefined) recordingResolution.value = data.recording_resolution;
  }

  /**
   * Tambahkan warning ke antrian.
   * @param {string} level - 'critical' | 'warning' | 'info'
   * @param {string} code  - kode unik, misal 'CAMERA_LOST'
   * @param {string} message - pesan human-readable
   */
  function addWarning(level, code, message) {
    // Jika warning dengan code yang sama sudah ada, update timestamp-nya saja
    const existing = warnings.value.find(w => w.code === code);
    if (existing) {
      existing.timestamp = Date.now();
      existing.message = message;
      return;
    }
    warnings.value.unshift({
      id: `${code}_${Date.now()}`,
      level,
      code,
      message,
      timestamp: Date.now(),
    });
    // Batasi maksimal 10 warning
    if (warnings.value.length > 10) warnings.value.pop();
  }

  /** Hapus warning berdasarkan code */
  function clearWarning(code) {
    warnings.value = warnings.value.filter(w => w.code !== code);
  }

  /** Hapus semua warning */
  function clearAllWarnings() {
    warnings.value = [];
  }

  function toggleSimulation() {
    isSimulating.value = !isSimulating.value;
    if (isSimulating.value) {
      simInterval = setInterval(() => {
        // Mock movement
        heading.value = (heading.value + (Math.random() - 0.4) * 2 + 360) % 360;
        sog.value = Math.max(0, sog.value + (Math.random() - 0.5) * 0.1);

        // Mock attitude
        pitch.value = Math.sin(Date.now() / 1000) * 5;
        roll.value = Math.cos(Date.now() / 1000) * 8;

        // Mock battery drain
        if (batteryPct.value > 0) batteryPct.value -= 0.001;

        // Mock GPS
        satellites.value = 12 + Math.floor(Math.random() * 3);
        gpsFix.value = 3;
        signalStrength.value = -60 + Math.floor(Math.random() * 10);
        // Mock Nav
        xte.value = Math.sin(Date.now() / 2000) * 1.5;
        dtw.value = Math.max(0, dtw.value - 0.05);
        if (dtw.value <= 0) {
          dtw.value = 200;
          nextWp.value = (nextWp.value % 7) + 1;
        }

        // Mock Engines
        thrusterL.value = 40 + Math.random() * 20;
        thrusterR.value = 40 + Math.random() * 20;
        rpmL.value = 1000 + thrusterL.value * 10;
        rpmR.value = 1000 + thrusterR.value * 10;
      }, 100);
    } else {
      if (simInterval) clearInterval(simInterval);
      thrusterL.value = 0;
      thrusterR.value = 0;
      rpmL.value = 0;
      rpmR.value = 0;
    }
  }

  return {
    lat, lng, heading, sog, cog,
    pitch, roll, yaw,
    batteryPct, batteryVolt,
    gpsFix, satellites, signalStrength,
    xte, dtw, nextWp,
    thrusterL, thrusterR, rpmL, rpmR,
    isConnected, isArmed, mode,
    isRecording, recordingFilename, recordingResolution,
    cameraConnected, asvConnected,
    warnings,
    isGpsValid, batteryColor, isSimulating,
    updateTelemetry, toggleSimulation,
    addWarning, clearWarning, clearAllWarnings,
  };
});
