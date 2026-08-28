<script setup>
import { onMounted, onUnmounted, watch } from "vue";
import { useVesselStore } from "@/stores/vesselStore";
import { useMissionStore } from "@/stores/missionStore";
import { useScoringStore } from "@/stores/scoringStore";
import { useWebsocketStore } from "@/stores/websocketStore";
import {
  Navigation,
  Compass,
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
  AlertTriangle,
  CheckCircle,
  X,
} from "lucide-vue-next";

import MetricCard from "../components/ui/MetricCard.vue";
import StatusBadge from "../components/ui/StatusBadge.vue";
import ProgressBar from "../components/ui/ProgressBar.vue";
import ArmingControl from "../components/monitoring/ArmingControl.vue";
import ControlSourceControl from "../components/monitoring/ControlSourceControl.vue";
import GeotagPanel from "../components/monitoring/GeotagPanel.vue";
import VideoCard from "../components/monitoring/VideoCard.vue";

const vessel = useVesselStore();
const mission = useMissionStore();
const scoring = useScoringStore();
const wsStore = useWebsocketStore();
</script>


<template>
  <div class="p-6 h-full overflow-y-auto space-y-6">
    <!-- Header Section -->
    <div class="flex justify-between items-end">
      <div>
        <h1 class="text-3xl font-bold text-(--text-primary) tracking-tight">
         ROBOTIKA
          <span class="text-primary/50 text-xl font-light">TIM-1</span>
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
      <div class="col-span-12 lg:col-span-8 grid grid-cols-2 lg:grid-cols-5 gap-4">
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
          label="COURSE OVER GROUND"
          :value="vessel.cogValid ? vessel.cog.toFixed(2) : '—'"
          unit="DEG"
          :icon="Compass"
          color="success"
          :note="vessel.cogValid ? '' : 'kapal terlalu pelan'"
        />
        <MetricCard
          label="BATTERY"
          :value="vessel.batteryVolt.toFixed(2)"
          unit="V"
          :icon="Battery"
          :color="vessel.batteryVolt > 22 ? 'success' : 'danger'"
        />
        <MetricCard
          label="TOTAL SCORE"
          :value="(isFinite(scoring.totalScore) ? scoring.totalScore : 0).toFixed(2)"
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
                >{{ mission.activeStepLabel }}</span
              >
              <span class="text-xs text-(--text-secondary)">{{ mission.progressPct }}% Complete</span>
            </div>
            <ProgressBar :progress="mission.progressPct" color="primary" />
          </div>
        </div>
        <div class="mt-6 flex gap-2">
          <button
            v-if="mission.missionStatus === 'IDLE' || mission.missionStatus === 'ABORTED' || mission.missionStatus === 'FINISHED'"
            @click="mission.startMission()"
            class="btn-primary flex-1 py-2 text-xs uppercase tracking-tighter"
          >
            Start Run
          </button>
          <button
            v-else-if="mission.missionStatus === 'RUNNING'"
            @click="mission.pauseMission()"
            class="bg-warning hover:bg-yellow-500 text-slate-900 font-bold flex-1 py-2 rounded-lg text-xs uppercase tracking-tighter transition-all"
          >
            Pause
          </button>
          <button
            v-else-if="mission.missionStatus === 'PAUSED'"
            @click="mission.resumeMission()"
            class="bg-success hover:bg-emerald-400 text-slate-900 font-bold flex-1 py-2 rounded-lg text-xs uppercase tracking-tighter transition-all"
          >
            Resume
          </button>
          <router-link
            to="/mission"
            class="bg-(--bg-secondary) hover:bg-slate-600 text-(--text-primary) px-3 py-2 rounded-lg transition-all flex items-center justify-center"
            title="Open Mission Control"
          >
            <ChevronRight class="w-4 h-4" />
          </router-link>
        </div>
      </div>

      <!-- Geo-tag: seluruh field "Position and Mission Imaging Infos" dalam satu
           baris penuh, sengaja diberi lebar penuh agar mudah dibaca & di-screenshot. -->
      <div class="col-span-12">
        <GeotagPanel />
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
        <VideoCard
          src="http://localhost:3000/api/v1/video/stream"
          title="FPV CAM"
          labelColor="blue"
          aspect="aspect-video"
          objectFit="object-cover"
        />
      </div>

      <!-- Right Sidebar: Arming Control + Alerts -->
      <div class="col-span-12 lg:col-span-3 space-y-4">
        <!-- ARM / DISARM Control -->
        <ArmingControl />

        <!-- Sumber kendali manual: Mini PC vs Remote RC fisik.
             Ditaruh tepat di bawah FLIGHT CONTROLLER karena satu kelompok
             pertanyaan dengan ARM/DISARM & mode: siapa yang memegang kapal. -->
        <ControlSourceControl />

        <!-- 3-in-1 Waypoint Determination Panel -->
        <div class="glass-card p-4 space-y-3 border-t-4 border-t-primary">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold uppercase tracking-widest text-(--text-primary) flex items-center gap-1.5">
              <MapPin class="w-4 h-4 text-primary" />
              Waypoint Control
            </span>
            <span class="text-[9px] px-2 py-0.5 rounded bg-primary/10 text-primary font-bold">HYBRID AI</span>
          </div>

          <div class="grid grid-cols-1 gap-2">
            <!-- Method 1: Relative Meters -->
            <button
              @click="wsStore.setRelativeWaypoints([
                { x: 15, y: 0 },
                { x: 30, y: 5 },
                { x: 45, y: -5 }
              ])"
              class="w-full text-left p-2.5 rounded-lg border bg-primary/5 border-primary/20 hover:bg-primary/15 transition-all text-xs font-bold flex items-center justify-between text-(--text-primary)"
            >
              <span>📐 Set Meter Course (15m, 30m, 45m)</span>
              <ChevronRight class="w-3.5 h-3.5 text-primary" />
            </button>

            <!-- Method 3: Save Current GPS Spot -->
            <button
              @click="wsStore.saveCurrentWaypoint()"
              class="w-full text-left p-2.5 rounded-lg border bg-warning/5 border-warning/20 hover:bg-warning/15 transition-all text-xs font-bold flex items-center justify-between text-(--text-primary)"
            >
              <span>📍 Save Current GPS Spot</span>
              <MapPin class="w-3.5 h-3.5 text-warning" />
            </button>
          </div>
        </div>

        <!-- Alerts Panel -->
        <div class="glass-card p-5 border-t-4 border-t-danger">

          <div class="flex items-center justify-between gap-2 mb-4">
            <div class="flex items-center gap-2">
              <ShieldAlert class="w-5 h-5 text-danger" />
              <span
                class="text-sm font-bold uppercase tracking-widest text-(--text-primary)"
                >System Alerts</span
              >
            </div>
            <!-- Badge jumlah warning -->
            <span v-if="vessel.warnings.length > 0"
              class="bg-danger text-white text-[9px] font-black px-2 py-0.5 rounded-full animate-pulse">
              {{ vessel.warnings.length }}
            </span>
            <button v-if="vessel.warnings.length > 0"
              @click="vessel.clearAllWarnings()"
              class="text-[9px] text-(--text-muted) hover:text-danger transition-colors"
              title="Dismiss semua alert">
              <X class="w-3.5 h-3.5" />
            </button>
          </div>

          <div class="space-y-2 max-h-[320px] overflow-y-auto">
            <!-- Dynamic warnings dari vesselStore -->
            <transition-group name="alert-list">
              <div
                v-for="w in vessel.warnings"
                :key="w.id"
                :class="[
                  'p-3 rounded-lg border relative',
                  w.level === 'critical' ? 'bg-danger/10 border-danger/20' :
                  w.level === 'warning'  ? 'bg-warning/10 border-warning/20' :
                                           'bg-primary/10 border-primary/20'
                ]">
                <div class="flex items-start justify-between gap-2">
                  <div class="flex-1 min-w-0">
                    <span :class="[
                      'text-[9px] font-black uppercase tracking-wider block mb-1',
                      w.level === 'critical' ? 'text-danger' :
                      w.level === 'warning'  ? 'text-warning' : 'text-primary'
                    ]">
                      <AlertTriangle v-if="w.level !== 'info'" class="w-2.5 h-2.5 inline mr-0.5" />
                      {{ w.level === 'critical' ? 'KRITIS' : w.level === 'warning' ? 'WARNING' : 'INFO' }}
                      <span class="opacity-50 ml-1">{{ w.code }}</span>
                    </span>
                    <p class="text-[10px] text-(--text-primary) leading-relaxed">{{ w.message }}</p>
                  </div>
                  <button @click="vessel.clearWarning(w.code)"
                    class="shrink-0 text-(--text-muted) hover:text-danger transition-colors mt-0.5">
                    <X class="w-3 h-3" />
                  </button>
                </div>
              </div>
            </transition-group>

            <!-- Fallback: semua nominal -->
            <div
              v-if="vessel.warnings.length === 0 && vessel.isConnected && wsStore.status === 'CONNECTED'"
              class="p-3 bg-success/10 border border-success/20 rounded-lg"
            >
              <span class="text-[10px] font-bold text-success uppercase">OK</span>
              <p class="text-xs text-(--text-primary) mt-1">Semua sistem nominal</p>
            </div>

            <!-- Static: FC tidak terhubung -->
            <div
              v-if="!vessel.isConnected"
              class="p-3 bg-danger/10 border border-danger/20 rounded-lg"
            >
              <span class="text-[10px] font-bold text-danger uppercase">Critical</span>
              <p class="text-xs text-(--text-primary) mt-1">Flight Controller tidak terhubung</p>
            </div>

            <!-- Static: WS backend putus -->
            <div
              v-if="wsStore.status !== 'CONNECTED'"
              class="p-3 bg-warning/10 border border-warning/20 rounded-lg"
            >
              <span class="text-[10px] font-bold text-warning uppercase">Warning</span>
              <p class="text-xs text-(--text-primary) mt-1">WebSocket terputus dari backend</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.alert-list-enter-active,
.alert-list-leave-active {
  transition: all 0.3s ease;
}
.alert-list-enter-from {
  opacity: 0;
  transform: translateX(-10px);
}
.alert-list-leave-to {
  opacity: 0;
  transform: translateX(10px);
  max-height: 0;
}
</style>
