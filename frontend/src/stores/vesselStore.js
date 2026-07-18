import { defineStore } from "pinia";
import { ref, computed } from "vue";

export const useVesselStore = defineStore("vessel", () => {
  // Telemetry State
  const lat = ref(-6.2088);
  const lng = ref(106.8456);
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
    if (data.lat !== undefined) lat.value = data.lat;
    if (data.lng !== undefined) lng.value = data.lng;
    if (data.heading !== undefined) heading.value = data.heading;
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
    isGpsValid, batteryColor, isSimulating,
    updateTelemetry, toggleSimulation
  };
});
