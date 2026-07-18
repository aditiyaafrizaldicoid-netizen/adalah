import { defineStore } from "pinia";
import { ref } from "vue";
import api from "@/services/api";

export const useCalibrationStore = defineStore("calibration", () => {
  // Current Active Calibration State
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
  
  // Database Profiles State
  const savedProfiles = ref([]);
  const isLoading = ref(false);

  async function fetchProfiles() {
    isLoading.value = true;
    try {
      const res = await api.get('/calibration/profiles');
      savedProfiles.value = res.data.data || [];
    } catch (err) {
      console.error("Failed to fetch profiles:", err);
    } finally {
      isLoading.value = false;
    }
  }

  async function saveProfile(name, isDefault = false) {
    try {
      const payload = {
        name,
        is_default: isDefault,
        imu_profile: imuProfile.value,
        gps_offset: gpsOffset.value,
        camera_settings: cameraSettings.value,
        thruster_trim: thrusterTrim.value
      };
      await api.post('/calibration/profiles', payload);
      await fetchProfiles();
    } catch (err) {
      console.error("Failed to save profile:", err);
      throw err;
    }
  }
  
  async function deleteProfile(id) {
    try {
      await api.delete(`/calibration/profiles/${id}`);
      await fetchProfiles();
    } catch (err) {
      console.error("Failed to delete profile:", err);
      throw err;
    }
  }

  function loadProfileToState(profile) {
    if (profile.imu_profile) imuProfile.value = profile.imu_profile;
    if (profile.gps_offset) gpsOffset.value = profile.gps_offset;
    if (profile.camera_settings) cameraSettings.value = profile.camera_settings;
    if (profile.thruster_trim) thrusterTrim.value = profile.thruster_trim;
  }

  return { 
    imuProfile, gpsOffset, cameraSettings, thrusterTrim, 
    savedProfiles, isLoading,
    fetchProfiles, saveProfile, deleteProfile, loadProfileToState 
  };
});
