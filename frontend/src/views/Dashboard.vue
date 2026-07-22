<script setup>
import { ref, onMounted } from "vue";
import { useVesselStore } from "@/stores/vesselStore";
import { useMissionStore } from "@/stores/missionStore";
import { useScoringStore } from "@/stores/scoringStore";
import { useWebsocketStore } from "@/stores/websocketStore";
import {
  Navigation,
  Battery,
  MapPin,
  Zap,
  Activity,
  Trophy,
  ChevronRight,
  ShieldAlert,
  Wifi,
  WifiOff,
  Video,
  VideoOff,
  CircleDot,
} from "lucide-vue-next";

import MetricCard from "../components/ui/MetricCard.vue";
import StatusBadge from "../components/ui/StatusBadge.vue";
import ProgressBar from "../components/ui/ProgressBar.vue";
import ArmingControl from "../components/monitoring/ArmingControl.vue";

const vessel = useVesselStore();
const mission = useMissionStore();
const scoring = useScoringStore();
const wsStore = useWebsocketStore();

const selectedRes = ref('640x480');
const handleToggleRecord = () => {
  const [w, h] = selectedRes.value.split('x');
  wsStore.toggleRecording(parseInt(w), parseInt(h));
};

onMounted(() => {
  // Start simulation if needed
});
</script>

<template>
  <div class="p-6 h-full overflow-y-auto space-y-6">
    <!-- Header Section -->
    <div class="flex justify-between items-end">
      <div>
        <h1 class="text-3xl font-bold text-(--text-primary) tracking-tight">
          DASHBOARD
          <span class="text-primary/50 text-xl font-light">OVERVIEW</span>
        </h1>
        <p
          class="text-(--text-secondary) text-sm mt-1 uppercase tracking-widest font-bold"
        >
          Autonomous Surface Vessel Ground Station
        </p>
      </div>
      <div class="flex items-center gap-3">
        <!-- WebSocket Status -->
        <div
          :class="[
            'flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border',
            wsStore.status === 'CONNECTED'
              ? 'bg-success/10 text-success border-success/30'
              : 'bg-danger/10 text-danger border-danger/30',
          ]"
        >
          <component
            :is="wsStore.status === 'CONNECTED' ? Wifi : WifiOff"
            class="w-3.5 h-3.5"
          />
          {{ wsStore.status }}
        </div>
        <!-- ARM Badge -->
        <div
          :class="[
            'flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-full border',
            vessel.isArmed
              ? 'bg-danger/10 text-danger border-danger/30 animate-pulse'
              : 'bg-(--bg-secondary) text-(--text-secondary) border-(--border-subtle)',
          ]"
        >
          <div
            :class="[
              'w-2 h-2 rounded-full',
              vessel.isArmed ? 'bg-danger' : 'bg-(--text-muted)',
            ]"
          />
          {{ vessel.isArmed ? "ARMED" : "DISARMED" }}
        </div>
        <StatusBadge
          label="GPS"
          :status="vessel.gpsFix > 0 ? 'success' : 'danger'"
          :value="`FIX: ${vessel.gpsFix}`"
        />
        <StatusBadge
          label="MISI"
          :status="mission.missionStatus === 'RUNNING' ? 'warning' : 'info'"
          :value="mission.missionStatus"
        />
      </div>
    </div>

    <!-- Main Grid -->
    <div class="grid grid-cols-12 gap-6">
      <!-- Telemetry Highlights -->
      <div class="col-span-12 lg:col-span-8 grid grid-cols-4 gap-4">
        <MetricCard
          label="SPEED OVER GROUND"
          :value="vessel.sog.toFixed(2)"
          unit="KNOTS"
          :icon="Activity"
          color="primary"
          trend="+0.2"
        />
        <MetricCard
          label="HEADING"
          :value="vessel.heading.toFixed(2)"
          unit="DEG"
          :icon="Navigation"
          color="warning"
        />
        <MetricCard
          label="BATTERY"
          :value="vessel.batteryPct.toFixed(2)"
          unit="%"
          :icon="Battery"
          :color="vessel.batteryPct > 20 ? 'success' : 'danger'"
        />
        <MetricCard
          label="TOTAL SCORE"
          :value="scoring.totalScore.toFixed(2)"
          unit="PTS"
          :icon="Trophy"
          color="primary"
        />
      </div>

      <!-- Live Mission Progress -->
      <div
        class="col-span-12 lg:col-span-4 glass-card p-5 flex flex-col justify-between border-l-4 border-l-primary"
      >
        <div>
          <div class="flex justify-between items-center mb-4">
            <span
              class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest"
              >Misi Progress</span
            >
            <span class="text-primary font-mono font-bold">{{
              mission.formattedTime
            }}</span>
          </div>
          <div class="space-y-4">
            <div class="flex justify-between items-end">
              <span class="text-sm font-semibold text-(--text-primary)"
                >Buoy 04 / 10</span
              >
              <span class="text-xs text-(--text-secondary)">40% Complete</span>
            </div>
            <ProgressBar :progress="40" color="primary" />
          </div>
        </div>
        <div class="mt-6 flex gap-2">
          <button
            v-if="mission.missionStatus !== 'RUNNING'"
            @click="mission.startMission()"
            class="btn-primary flex-1 py-2 text-xs uppercase tracking-tighter"
          >
            Start Run
          </button>
          <button
            v-else
            @click="mission.stopMission()"
            class="bg-warning hover:bg-yellow-500 text-slate-900 font-bold flex-1 py-2 rounded-lg text-xs uppercase tracking-tighter transition-all"
          >
            Pause
          </button>
          <button
            class="bg-(--bg-secondary) hover:bg-slate-600 text-(--text-primary) px-3 py-2 rounded-lg transition-all"
          >
            <ChevronRight class="w-4 h-4" />
          </button>
        </div>
      </div>

      <!-- Map & Video Feed -->
      <div
        class="col-span-12 lg:col-span-9 grid grid-cols-1 md:grid-cols-1 gap-6"
      >
        <!-- Map -->
        <!-- <div class="glass-card min-h-[400px] relative overflow-hidden group">
          <div class="absolute inset-0 bg-(--bg-secondary)/50 flex items-center justify-center flex-col">
            <MapPin class="w-12 h-12 text-primary animate-bounce mb-4" />
            <span class="text-(--text-secondary) font-mono text-sm">GRID MAP</span>
          </div>
      
          <div class="absolute top-4 left-4 flex flex-col gap-2">
            <div class="bg-(--bg-secondary)/80 backdrop-blur p-3 rounded-lg border border-(--border-subtle)">
              <span class="text-[10px] text-(--text-secondary) block uppercase font-bold">Coordinates</span>
              <span class="text-xs font-mono text-(--text-primary)">{{ vessel.lat.toFixed(6) }}, {{ vessel.lng.toFixed(6) }}</span>
            </div>
          </div>
        </div> -->

        <!-- Video Stream -->
        <div
          class="glass-card relative overflow-hidden border border-(--border-subtle) rounded-xl bg-slate-900 flex items-center justify-center w-full aspect-video"
        >
          <img
            src="http://localhost:3000/api/v1/video/stream"
            class="w-full h-full object-cover"
            onerror="
              this.style.display = 'none';
              this.nextElementSibling.style.display = 'flex';
            "
            onload="
              this.style.display = 'block';
              this.nextElementSibling.style.display = 'none';
            "
          />
          <div
            class="absolute inset-0 text-slate-500 font-mono text-sm flex flex-col items-center justify-center"
            style="display: none"
          >
            <span class="animate-pulse tracking-widest">NO VIDEO SIGNAL</span>
          </div>
          <!-- Video Overlay UI -->
          <div class="absolute top-4 right-4 flex items-center gap-2 z-10">
            <!-- Recording Indicator Badge -->
            <span v-if="vessel.isRecording"
              class="flex items-center gap-1.5 bg-red-600/90 text-white text-[10px] px-2.5 py-1 rounded font-black tracking-widest animate-pulse border border-red-400 shadow-lg">
              <CircleDot class="w-3.5 h-3.5 text-white" />
              REC {{ vessel.recordingResolution }}
            </span>

            <!-- Resolution Picker -->
            <select v-if="!vessel.isRecording" v-model="selectedRes"
              class="text-[10px] font-mono bg-black/80 border border-white/20 text-white rounded px-2 py-1 focus:outline-none opacity-80 hover:opacity-100 transition-opacity">
              <option value="640x480">640x480 (SD)</option>
              <option value="1280x720">1280x720 (HD)</option>
              <option value="1920x1080">1920x1080 (FHD)</option>
            </select>

            <!-- Record Button -->
            <button @click="handleToggleRecord"
              :class="[
                'px-3 py-1 rounded flex items-center gap-1.5 text-[10px] font-bold tracking-wider transition-all shadow-lg cursor-pointer',
                vessel.isRecording 
                  ? 'bg-red-600 text-white hover:bg-red-700 animate-pulse border border-red-400' 
                  : 'bg-black/80 text-white border border-white/20 hover:bg-red-600 hover:text-white'
              ]"
              :title="vessel.isRecording ? 'Stop Recording Raw Stream' : 'Record Raw Stream (No Object Detection)'">
              <VideoOff v-if="vessel.isRecording" class="w-3.5 h-3.5" />
              <Video v-else class="w-3.5 h-3.5 text-red-500" />
              <span>{{ vessel.isRecording ? 'STOP REC' : 'REC MP4' }}</span>
            </button>

            <span
              class="bg-danger/80 text-white text-[10px] px-2 py-1 rounded font-bold animate-pulse tracking-widest"
              >LIVE</span
            >
            <span
              class="bg-black/50 backdrop-blur border border-white/10 text-white text-[10px] px-2 py-1 rounded font-mono tracking-widest"
              >FPV CAM</span
            >
          </div>
          <!-- Crosshair -->
          <div
            class="absolute inset-0 flex items-center justify-center pointer-events-none opacity-30"
          >
            <div class="w-8 h-px bg-white"></div>
            <div class="h-8 w-px bg-white absolute"></div>
            <div
              class="w-12 h-12 border border-white rounded-full absolute"
            ></div>
          </div>
        </div>
      </div>

      <!-- Right Sidebar: Arming Control + Alerts -->
      <div class="col-span-12 lg:col-span-3 space-y-4">
        <!-- ARM / DISARM Control -->
        <ArmingControl />

        <!-- Alerts Panel -->
        <div class="glass-card p-5 border-t-4 border-t-danger">
          <div class="flex items-center gap-2 mb-4">
            <ShieldAlert class="w-5 h-5 text-danger" />
            <span
              class="text-sm font-bold uppercase tracking-widest text-(--text-primary)"
              >System Alerts</span
            >
          </div>
          <div class="space-y-3">
            <div
              v-if="!vessel.isConnected"
              class="p-3 bg-danger/10 border border-danger/20 rounded-lg"
            >
              <span class="text-[10px] font-bold text-danger uppercase"
                >Critical</span
              >
              <p class="text-xs text-(--text-primary) mt-1">
                Flight Controller tidak terhubung
              </p>
            </div>
            <div
              v-if="wsStore.status !== 'CONNECTED'"
              class="p-3 bg-warning/10 border border-warning/20 rounded-lg"
            >
              <span class="text-[10px] font-bold text-warning uppercase"
                >Warning</span
              >
              <p class="text-xs text-(--text-primary) mt-1">
                WebSocket terputus dari backend
              </p>
            </div>
            <div
              v-if="vessel.isConnected && wsStore.status === 'CONNECTED'"
              class="p-3 bg-success/10 border border-success/20 rounded-lg"
            >
              <span class="text-[10px] font-bold text-success uppercase"
                >OK</span
              >
              <p class="text-xs text-(--text-primary) mt-1">
                Semua sistem nominal
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
