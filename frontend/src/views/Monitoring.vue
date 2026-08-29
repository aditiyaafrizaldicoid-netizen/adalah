<script setup>
import { useVesselStore } from '@/stores/vesselStore';
import AttitudeIndicator from "../components/monitoring/AttitudeIndicator.vue";
import CompassRose from "../components/monitoring/CompassRose.vue";
import SpeedGauge from "../components/monitoring/SpeedGauge.vue";
import BatteryWidget from "../components/monitoring/BatteryWidget.vue";
import GpsWidget from "../components/monitoring/GpsWidget.vue";
import NavAnalysis from "../components/monitoring/NavAnalysis.vue";
import EngineMonitor from "../components/monitoring/EngineMonitor.vue";
import VideoCard from "../components/monitoring/VideoCard.vue";
import TelemetryChart from "../components/monitoring/TelemetryChart.vue";
import { Activity } from "lucide-vue-next";
import { VIDEO_STREAM_URL } from "@/config/api";

const vessel = useVesselStore();
</script>

<template>
  <div class="p-3 sm:p-6 h-full overflow-y-auto space-y-4 sm:space-y-6">
    <div class="flex justify-between items-center">
      <h1 class="text-2xl font-bold text-(--text-primary) tracking-tight flex items-center gap-3">
        <Activity class="text-primary w-6 h-6" />
        REAL-TIME MONITORING
      </h1>
      <div class="text-xs font-mono text-(--text-secondary) uppercase tracking-widest">
        Telemetry Stream: ACTIVE
      </div>
    </div>

    <div class="grid grid-cols-12 gap-6">
      <!-- Main Visuals -->
      <div class="col-span-12 lg:col-span-8 grid grid-cols-2 gap-6">
        <div class="glass-card p-6 flex flex-col items-center justify-center">
          <span class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest mb-4">Attitude
            Indicator</span>
          <AttitudeIndicator :pitch="vessel.pitch" :roll="vessel.roll" />
        </div>
        <div class="glass-card p-6 flex flex-col items-center justify-center">
          <span class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest mb-4">Compass Rose</span>
          <CompassRose :heading="vessel.heading" />
        </div>
      </div>

      <!-- Quick Widgets & Analysis -->
      <div class="col-span-12 lg:col-span-4 flex flex-col gap-6">
        <div class="glass-card p-6 flex justify-around items-center">
          <SpeedGauge :speed="vessel.sog" />
          <div class="h-24 w-px bg-card"></div>
          <div class="flex flex-col items-center">
            <span class="text-2xl font-black text-(--text-primary) font-mono">{{ vessel.cog.toFixed(2) }}°</span>
            <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest mt-1">Course</span>
          </div>
        </div>

        <NavAnalysis :xte="vessel.xte" :dtw="vessel.dtw" :nextWp="vessel.nextWp" />
        <EngineMonitor :thrusterL="vessel.thrusterL" :thrusterR="vessel.thrusterR" :rpmL="vessel.rpmL"
          :rpmR="vessel.rpmR" />

        <BatteryWidget :percentage="vessel.batteryPct" :voltage="vessel.batteryVolt" />
        <GpsWidget :lat="vessel.lat" :lng="vessel.lng" :fix="vessel.gpsFix" :satellites="vessel.satellites" />
      </div>

      <!-- Camera Feed -->
      <div class="col-span-12">
        <VideoCard
          :src="VIDEO_STREAM_URL"
          title="PRIMARY CAMERA"
          labelColor="teal"
          aspect="aspect-video"
          objectFit="object-contain"
        />
      </div>


      <!-- History Chart -->
      <div class="col-span-12 h-75">
        <TelemetryChart />
      </div>

    </div>
  </div>
</template>
