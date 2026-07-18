import { defineStore } from "pinia";
import { ref } from "vue";

export const useCalibrationStore = defineStore("calibration", () => {
  const imuProfile = ref({
    accel_offset: [0, 0, 0],
    gyro_offset: [0, 0, 0],
    mag_hard_iron: [0, 0, 0],
    mag_soft_iron: [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
  });

  const gpsOffset = ref({ lat: 0, lng: 0 });
  const cameraSettings = ref({
    surface: { brightness: 50, contrast: 50, exposure: 'auto' },
    underwater: { brightness: 50, contrast: 70, exposure: 'auto' }
  });

  const thrusterTrim = ref({ port: 0, starboard: 0 });

  function saveProfile(name) {
    console.log("Saving calibration profile:", name);
  }

  return { imuProfile, gpsOffset, cameraSettings, thrusterTrim, saveProfile };
});
