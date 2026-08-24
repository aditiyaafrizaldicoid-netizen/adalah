<script setup>
import { ref, watch } from 'vue';
import { Settings2, Compass, MapPin, Camera, Zap, Cpu, Sliders } from "lucide-vue-next";

// Sub-components
import ImuCalibration from "../components/calibration/ImuCalibration.vue";
import GpsCalibration from "../components/calibration/GpsCalibration.vue";
import CameraCalibration from "../components/calibration/CameraCalibration.vue";
import ThrusterCalibration from "../components/calibration/ThrusterCalibration.vue";
import CalibrationProfile from "../components/calibration/CalibrationProfile.vue";
import ChannelConfig from "../components/calibration/ChannelConfig.vue";
import PidTuningCard from "../components/calibration/PidTuningCard.vue";
import { useRouter, useRoute } from 'vue-router';
const router = useRouter();
const route = useRoute();
const activeTab = ref('channel');

const tabs = [
  { id: 'pid', name: 'AI PID Tuning', icon: Sliders },
  { id: 'channel', name: 'Channel Map', icon: Cpu },
  { id: 'imu', name: 'IMU / Attitude', icon: Compass },
  { id: 'gps', name: 'GPS Offset', icon: MapPin },
  { id: 'camera', name: 'Vision / Camera', icon: Camera },
  { id: 'thruster', name: 'Thruster / Trim', icon: Zap },
  { id: 'profile', name: 'Profiles', icon: Settings2 },
];
const changeTab = (tabId) => {
  activeTab.value = tabId;
  router.push({ name: 'Calibration', query: { tab: tabId } });
};
// watch (immediate) instead of onMounted: on a fresh full page load, the router's
// initial navigation may not have finished resolving yet when onMounted fires, so
// route.query.tab can still read as empty at that exact instant — silently falling
// back to the ref's default ('channel') instead of the URL's ?tab=... value. watch
// re-syncs reactively whenever route.query.tab actually becomes available (and also
// on subsequent query changes, e.g. browser back/forward), not just once at mount.
watch(() => route.query.tab, (tab) => {
  activeTab.value = tab || 'pid';
}, { immediate: true })
</script>

<template>
  <div class="p-6 h-full flex flex-col gap-6 overflow-hidden">
    <div>
      <h1 class="text-2xl font-bold text-(--text-primary) tracking-tight flex items-center gap-3">
        <Settings2 class="text-primary w-6 h-6" />
        SENSOR & AI CALIBRATION
      </h1>
      <p class="text-(--text-secondary) text-xs mt-1 uppercase tracking-widest font-bold">Hardware Fine-Tuning & AI PID Control</p>
    </div>

    <div class="flex-1 flex gap-6 overflow-hidden">
      <!-- Sidebar Tabs -->
      <div class="w-64 shrink-0 flex flex-col gap-2 overflow-y-auto pr-2">
        <button v-for="tab in tabs" :key="tab.id" @click="changeTab(tab.id)" :class="[
          'flex items-center gap-4 px-5 py-4 rounded-xl font-bold text-sm transition-all border shrink-0',
          activeTab === tab.id
            ? 'bg-primary text-slate-900 border-primary shadow-lg shadow-primary/10'
            : 'bg-card/50 text-(--text-secondary) border-(--border-subtle)/50 hover:bg-(--bg-secondary) hover:text-(--text-primary)'
        ]">
          <component :is="tab.icon" class="w-5 h-5" />
          {{ tab.name }}
        </button>
      </div>

      <!-- Content Area (Modular Components) -->
      <div class="flex-1 glass-card p-8 overflow-y-auto">
        <transition name="fade" mode="out-in">
          <div :key="activeTab">
            <PidTuningCard v-if="activeTab === 'pid'" />
            <ChannelConfig v-if="activeTab === 'channel'" />
            <ImuCalibration v-if="activeTab === 'imu'" />
            <GpsCalibration v-if="activeTab === 'gps'" />
            <CameraCalibration v-if="activeTab === 'camera'" />
            <ThrusterCalibration v-if="activeTab === 'thruster'" />
            <CalibrationProfile v-if="activeTab === 'profile'" />
          </div>
        </transition>
      </div>


    </div>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
