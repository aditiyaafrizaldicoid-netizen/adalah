<script setup>
import { useMissionStore } from '@/stores/missionStore';
import MissionTimeline from "../components/mission/MissionTimeline.vue";
import WaypointList from "../components/mission/WaypointList.vue";
import MissionPreset from "../components/mission/MissionPreset.vue";
import EmergencyStop from "../components/mission/EmergencyStop.vue";
import { 
  Flag, 
  Play, 
  Square, 
  RotateCcw,
  ListOrdered
} from "lucide-vue-next";

const mission = useMissionStore();
</script>

<template>
  <div class="p-6 h-full flex flex-col gap-6 overflow-hidden">
    <!-- Header Controls -->
    <div class="flex justify-between items-center bg-secondary/50 p-4 rounded-xl border border-(--border-subtle)/50 backdrop-blur-md">
      <div class="flex gap-4">
        <button 
          v-if="mission.missionStatus !== 'RUNNING'"
          @click="mission.startMission()" 
          class="flex items-center gap-2 bg-success text-slate-900 font-black px-6 py-2.5 rounded-lg hover:bg-emerald-400 transition-all shadow-lg shadow-success/20"
        >
          <Play class="w-5 h-5 fill-current" />
          START MISSION
        </button>
        <button 
          v-else
          @click="mission.pauseMission()" 
          class="flex items-center gap-2 bg-warning text-slate-900 font-black px-6 py-2.5 rounded-lg hover:bg-yellow-400 transition-all"
        >
          <Square class="w-5 h-5 fill-current" />
          PAUSE
        </button>
        
        <button 
          @click="mission.resetMission()" 
          class="flex items-center gap-2 bg-(--bg-secondary) text-(--text-primary) font-bold px-6 py-2.5 rounded-lg hover:bg-slate-600 transition-all"
        >
          <RotateCcw class="w-5 h-5" />
          RESET
        </button>
      </div>

      <div class="flex items-center gap-8 pr-4">
         <div class="text-right">
           <span class="text-[10px] text-(--text-secondary) uppercase font-black block">ELAPSED TIME</span>
           <span class="text-2xl font-mono font-black text-(--text-primary)">{{ mission.formattedTime }}</span>
         </div>
      </div>
    </div>

    <div class="flex-1 grid grid-cols-12 gap-6 overflow-hidden">
      <!-- Mission Timeline (Sub-component) -->
      <div class="col-span-12 lg:col-span-3 glass-card p-6 overflow-y-auto">
        <MissionTimeline :steps="mission.missionSteps" :currentStep="mission.currentStep" />
      </div>

      <!-- Waypoint & Preset (Sub-components) -->
      <div class="col-span-12 lg:col-span-5 flex flex-col gap-6 overflow-hidden">
        <div class="flex-1 overflow-hidden">
           <WaypointList :waypoints="mission.waypoints" />
        </div>
        <MissionPreset />
      </div>

      <!-- Emergency & Logs -->
      <div class="col-span-12 lg:col-span-4 flex flex-col gap-6 overflow-hidden">
        <EmergencyStop @stop="mission.resetMission()" />
        
        <div class="glass-card flex-1 flex flex-col overflow-hidden">
          <div class="p-4 border-b border-(--border-subtle) flex justify-between items-center">
            <span class="text-xs font-black text-(--text-primary) uppercase tracking-widest flex items-center gap-2">
              <ListOrdered class="w-4 h-4 text-primary" />
              Activity Log
            </span>
          </div>
          <div class="flex-1 overflow-y-auto p-4 space-y-3 font-mono text-[10px]">
             <div v-for="i in 10" :key="i" class="text-(--text-secondary)">
                <span class="text-primary">[{{ 14+i }}:20:01]</span> Log message {{ i }} for KKI mission run.
             </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
