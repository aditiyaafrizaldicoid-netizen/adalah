<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';
import GridMap from '../components/mapping/GridMap.vue';
import WaypointEditor from '../components/mapping/WaypointEditor.vue';
import { useMissionStore } from '@/stores/missionStore';
import {
  Map as MapIcon,
  Layers,
  Download,
  CheckCircle2
} from 'lucide-vue-next';

const mission = useMissionStore();
const router = useRouter();
const activeTool = ref('select');
const visibleLayers = ref(['grid', 'vessel', 'buoys', 'trail']);
const uploadFeedback = ref('');  // toast feedback setelah upload waypoints

const toggleLayer = (layer) => {
  const index = visibleLayers.value.indexOf(layer);
  if (index > -1) visibleLayers.value.splice(index, 1);
  else visibleLayers.value.push(layer);
};

// ── WaypointEditor event handlers ──────────────────────────────────────────
function handleWaypointDelete(index) {
  mission.removeWaypoint(index);
}

function handleWaypointClear() {
  mission.clearWaypoints();
}

// "Send to Mission" — konversi semua waypoints ke GOTO_GPS steps lalu navigasi ke MissionControl
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
  a.download = `asv_waypoints_${new Date().toISOString().slice(0,10)}.geojson`;
  a.click();
  URL.revokeObjectURL(url);
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
        <div class="flex items-center gap-2 px-3 py-1.5 bg-card/50 rounded-full border border-(--border-subtle)">
          <Layers class="w-3.5 h-3.5 text-(--text-secondary)" />
          <div class="flex gap-2">
            <button 
              v-for="layer in ['grid', 'vessel', 'buoys', 'trail']" 
              :key="layer"
              @click="toggleLayer(layer)"
              :class="['text-[10px] font-bold uppercase px-2 py-0.5 rounded transition-all', visibleLayers.includes(layer) ? 'bg-primary/20 text-primary' : 'text-(--text-muted)']"
            >
              {{ layer }}
            </button>
          </div>
        </div>
        <button @click="downloadWaypoints" title="Download waypoints sebagai GeoJSON"
          :disabled="!mission.waypoints.length"
          class="bg-(--bg-secondary) hover:bg-slate-600 text-(--text-primary) p-2 rounded-lg transition-all disabled:opacity-30 disabled:cursor-not-allowed">
          <Download class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Map Area -->
    <div class="flex-1 relative overflow-hidden bg-background">
      <GridMap :width="1920" :height="1080" :visible-layers="visibleLayers" />
      
      <!-- Upload feedback toast -->
      <div v-if="uploadFeedback"
        class="absolute top-6 left-1/2 -translate-x-1/2 flex items-center gap-2 bg-success text-slate-900 px-4 py-2 rounded-full text-xs font-black shadow-lg z-20 animate-pulse">
        <CheckCircle2 class="w-4 h-4" /> {{ uploadFeedback }}
      </div>

      <!-- Waypoint Editor Component -->
      <div class="absolute top-6 right-6 w-72">
        <WaypointEditor
          :waypoints="mission.waypoints"
          @delete="handleWaypointDelete"
          @clear="handleWaypointClear"
          @upload="handleWaypointUpload"
        />
      </div>

      <!-- Map Mode Switcher -->
      <div class="absolute bottom-6 left-6 flex gap-2">
         <div class="bg-(--bg-secondary)/90 border border-(--border-subtle) p-1 rounded-xl flex">
            <button class="px-4 py-2 bg-primary text-slate-900 rounded-lg text-[10px] font-black uppercase">LIVE Tracking</button>
            <button class="px-4 py-2 text-(--text-secondary) text-[10px] font-black uppercase hover:text-(--text-primary) transition-all">Waypoint Editor</button>
            <button class="px-4 py-2 text-(--text-secondary) text-[10px] font-black uppercase hover:text-(--text-primary) transition-all">Playback</button>
         </div>
      </div>
    </div>
  </div>
</template>
