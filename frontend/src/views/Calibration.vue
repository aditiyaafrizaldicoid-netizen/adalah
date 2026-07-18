<script setup>
import { ref } from 'vue';
import { Settings2, Compass, MapPin, Camera, Zap, Cpu } from "lucide-vue-next";

// Sub-components
import ImuCalibration from "../components/calibration/ImuCalibration.vue";
import GpsCalibration from "../components/calibration/GpsCalibration.vue";
import CameraCalibration from "../components/calibration/CameraCalibration.vue";
import ThrusterCalibration from "../components/calibration/ThrusterCalibration.vue";
import ServoCalibration from "../components/calibration/ServoCalibration.vue";
import CalibrationProfile from "../components/calibration/CalibrationProfile.vue";
import ChannelConfig from "../components/calibration/ChannelConfig.vue";

const activeTab = ref('channel');

const tabs = [
  { id: 'channel', name: 'Channel Map', icon: Cpu },
  { id: 'imu', name: 'IMU / Attitude', icon: Compass },
  { id: 'gps', name: 'GPS Offset', icon: MapPin },
  { id: 'camera', name: 'Vision / Camera', icon: Camera },
  { id: 'thruster', name: 'Thruster / Trim', icon: Zap },
  { id: 'servo', name: 'Servo / Actuator', icon: Settings2 },
  { id: 'profile', name: 'Profiles', icon: Settings2 },
];
</script>

<template>
  <div class="p-6 h-full flex flex-col gap-6 overflow-hidden">
    <div>
      <h1 class="text-2xl font-bold text-(--text-primary) tracking-tight flex items-center gap-3">
        <Settings2 class="text-primary w-6 h-6" />
        SENSOR CALIBRATION
      </h1>
      <p class="text-(--text-secondary) text-xs mt-1 uppercase tracking-widest font-bold">Hardware Fine-Tuning & Alignment</p>
    </div>

    <div class="flex-1 flex gap-6 overflow-hidden">
      <!-- Sidebar Tabs -->
      <div class="w-64 shrink-0 flex flex-col gap-2 overflow-y-auto pr-2">
        <button 
          v-for="tab in tabs" 
          :key="tab.id"
          @click="activeTab = tab.id"
          :class="[
            'flex items-center gap-4 px-5 py-4 rounded-xl font-bold text-sm transition-all border shrink-0',
            activeTab === tab.id 
              ? 'bg-primary text-slate-900 border-primary shadow-lg shadow-primary/10' 
              : 'bg-card/50 text-(--text-secondary) border-(--border-subtle)/50 hover:bg-(--bg-secondary) hover:text-(--text-primary)'
          ]"
        >
          <component :is="tab.icon" class="w-5 h-5" />
          {{ tab.name }}
        </button>
      </div>

      <!-- Content Area (Modular Components) -->
      <div class="flex-1 glass-card p-8 overflow-y-auto">
        <transition name="fade" mode="out-in">
           <div :key="activeTab">
              <ChannelConfig v-if="activeTab === 'channel'" />
              <ImuCalibration v-if="activeTab === 'imu'" />
              <GpsCalibration v-if="activeTab === 'gps'" />
              <CameraCalibration v-if="activeTab === 'camera'" />
              <ThrusterCalibration v-if="activeTab === 'thruster'" />
              <ServoCalibration v-if="activeTab === 'servo'" />
              <CalibrationProfile v-if="activeTab === 'profile'" />
           </div>
        </transition>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
