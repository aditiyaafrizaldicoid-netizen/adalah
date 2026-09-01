<script setup>
import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import GridMap from '../components/mapping/GridMap.vue';
import WaypointEditor from '../components/mapping/WaypointEditor.vue';
import ArenaEditor from '../components/mapping/ArenaEditor.vue';
import GeofenceEditor from '../components/mapping/GeofenceEditor.vue';
import { useMissionStore } from '@/stores/missionStore';
import { useArenaStore } from '@/stores/arenaStore';
import {
  Map as MapIcon,
  Layers,
  Download,
  CheckCircle2,
  Flag,
  Navigation2,
  Shield,
} from 'lucide-vue-next';

const mission = useMissionStore();
const arenaStore = useArenaStore();
const router = useRouter();

// 'live' | 'waypoint' | 'arena' | 'geofence'
const mapMode = ref('waypoint');

const visibleLayers = ref(['grid', 'vessel', 'buoys', 'trail']);

const toggleLayer = (layer) => {
  const index = visibleLayers.value.indexOf(layer);
  if (index > -1) visibleLayers.value.splice(index, 1);
  else visibleLayers.value.push(layer);
};

// GridMap click mode: only route clicks in waypoint/arena mode
const gridMapMode = computed(() => {
  if (mapMode.value === 'waypoint') return 'waypoint';
  if (mapMode.value === 'arena') return 'arena';
  if (mapMode.value === 'geofence') return 'geofence';
  return 'none';
});

// ── WaypointEditor event handlers ──────────────────────────────────────────
const uploadFeedback = ref('');

function handleWaypointDelete(index) {
  mission.removeWaypoint(index);
}

function handleWaypointClear() {
  mission.clearWaypoints();
}

function handleWaypointUpload() {
  if (!mission.waypoints.length) return;
  mission.loadWaypointsAsMission();
  uploadFeedback.value = `${mission.waypoints.length} waypoint dikirim ke misi`;
  setTimeout(() => { uploadFeedback.value = ''; }, 3000);
  router.push({ name: 'MissionControl' });
}

// ── Download map as GeoJSON ─────────────────────────────────────────────────
function downloadWaypoints() {
  if (!mission.waypoints.length) return;
  const geojson = {
    type: 'FeatureCollection',
    features: mission.waypoints.map((wp, i) => ({
      type: 'Feature',
      properties: { name: `WP ${i + 1}` },
      geometry: { type: 'Point', coordinates: [wp.lng, wp.lat] }
    }))
  };
  const blob = new Blob([JSON.stringify(geojson, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `asv_waypoints_${new Date().toISOString().slice(0, 10)}.geojson`;
  a.click();
  URL.revokeObjectURL(url);
}

// Switch mode — clear arena tool when leaving arena mode
function setMode(mode) {
  if (mapMode.value === 'arena' && mode !== 'arena') {
    arenaStore.clearTool();
  }
  mapMode.value = mode;
}
</script>

<template>
  <div class="h-full flex flex-col overflow-hidden">
    <!-- Toolbar -->
    <div class="h-14 bg-secondary/80 backdrop-blur-xl border-b border-(--border-subtle)/50 flex items-center justify-between px-6 shrink-0">
      <div class="flex items-center gap-4">
        <div class="flex items-center gap-2 mr-4">
          <MapIcon class="w-5 h-5 text-primary" />
          <span class="text-sm font-bold text-(--text-primary) uppercase tracking-wider">Mission Mapping</span>
        </div>
      </div>

      <div class="flex items-center gap-4">
        <!-- Layer toggles -->
        <div class="flex items-center gap-2 px-3 py-1.5 bg-card/50 rounded-full border border-(--border-subtle)">
          <Layers class="w-3.5 h-3.5 text-(--text-secondary)" />
          <div class="flex gap-2">
            <button
              v-for="layer in ['grid', 'vessel', 'buoys', 'trail']"
              :key="layer"
              @click="toggleLayer(layer)"
              :class="['text-[10px] font-bold uppercase px-2 py-0.5 rounded transition-all',
                visibleLayers.includes(layer) ? 'bg-primary/20 text-primary' : 'text-(--text-muted)']">
              {{ layer }}
            </button>
          </div>
        </div>

        <!-- Download waypoints -->
        <button @click="downloadWaypoints" title="Download waypoints sebagai GeoJSON"
          :disabled="!mission.waypoints.length"
          class="bg-(--bg-secondary) hover:bg-slate-600 text-(--text-primary) p-2 rounded-lg transition-all disabled:opacity-30 disabled:cursor-not-allowed">
          <Download class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Map Area -->
    <div class="flex-1 relative overflow-hidden bg-background">
      <GridMap
        :width="1920"
        :height="1080"
        :visible-layers="visibleLayers"
        :map-mode="gridMapMode"
      />

      <!-- Toast feedback -->
      <div v-if="uploadFeedback"
        class="absolute top-6 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-success text-slate-900 px-4 py-2 rounded-full text-xs font-black shadow-lg z-20 animate-pulse">
        <CheckCircle2 class="w-4 h-4" /> {{ uploadFeedback }}
      </div>

      <!-- Right Panel — WaypointEditor or ArenaEditor -->
      <div class="absolute top-6 right-6 w-72 z-10">
        <WaypointEditor v-if="mapMode === 'waypoint'"
          :waypoints="mission.waypoints"
          @delete="handleWaypointDelete"
          @clear="handleWaypointClear"
          @upload="handleWaypointUpload"
        />
        <ArenaEditor v-else-if="mapMode === 'arena'" />
        <div v-else-if="mapMode === 'geofence'"
          class="glass-card p-4 max-h-[calc(100vh-12rem)] overflow-y-auto">
          <GeofenceEditor />
        </div>
      </div>

      <!-- Map Mode Switcher (bottom-left) -->
      <div class="absolute bottom-6 left-6 flex gap-2 z-10">
        <div class="bg-(--bg-secondary)/90 backdrop-blur-md border border-(--border-subtle) p-1 rounded-xl flex">
          <button
            @click="setMode('live')"
            :class="['px-4 py-2 rounded-lg text-[10px] font-black uppercase transition-all flex items-center gap-1.5',
              mapMode === 'live' ? 'bg-primary text-slate-900' : 'text-(--text-secondary) hover:text-(--text-primary)']">
            <span class="w-1.5 h-1.5 rounded-full bg-current"></span> LIVE Tracking
          </button>
          <button
            @click="setMode('waypoint')"
            :class="['px-4 py-2 rounded-lg text-[10px] font-black uppercase transition-all flex items-center gap-1.5',
              mapMode === 'waypoint' ? 'bg-primary text-slate-900' : 'text-(--text-secondary) hover:text-(--text-primary)']">
            <Navigation2 class="w-3 h-3" /> Waypoints
          </button>
          <button
            @click="setMode('arena')"
            :class="['px-4 py-2 rounded-lg text-[10px] font-black uppercase transition-all flex items-center gap-1.5',
              mapMode === 'arena' ? 'bg-emerald-500 text-slate-900' : 'text-(--text-secondary) hover:text-(--text-primary)']">
            <Flag class="w-3 h-3" /> Arena
          </button>
          <button
            @click="setMode('geofence')"
            :class="['px-4 py-2 rounded-lg text-[10px] font-black uppercase transition-all flex items-center gap-1.5',
              mapMode === 'geofence' ? 'bg-warning text-slate-900' : 'text-(--text-secondary) hover:text-(--text-primary)']">
            <Shield class="w-3 h-3" /> Geofence
          </button>
        </div>

        <!-- Geofence: penanda mode menaruh pusat -->
        <div v-if="mapMode === 'geofence'"
          class="flex items-center gap-2 px-3 py-2 bg-warning/20 border border-warning/40 rounded-xl text-[10px] text-warning font-bold backdrop-blur-md">
          <span class="w-2 h-2 rounded-full bg-warning animate-pulse"></span>
          KLIK PETA UNTUK MENARUH PUSAT
        </div>

        <!-- Arena mode active indicator -->
        <div v-if="mapMode === 'arena' && arenaStore.activePlaceTool"
          class="flex items-center gap-2 px-3 py-2 bg-emerald-500/20 border border-emerald-500/40 rounded-xl text-[10px] text-emerald-400 font-bold backdrop-blur-md">
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          {{ arenaStore.activePlaceTool.replace('_', ' ').toUpperCase() }} MODE
        </div>
      </div>
    </div>
  </div>
</template>
