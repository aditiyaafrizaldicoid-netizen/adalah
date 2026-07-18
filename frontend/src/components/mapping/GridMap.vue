<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue';
import { useVesselStore } from '@/stores/vesselStore';
import { useMissionStore } from '@/stores/missionStore';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

const props = defineProps({
  width: { type: Number, default: 800 },
  height: { type: Number, default: 600 },
  visibleLayers: { type: Array, default: () => ['grid', 'vessel', 'trail', 'buoys'] }
});

const vessel = useVesselStore();
const mission = useMissionStore();

const mapContainer = ref(null);
let map = null;
let asvMarker = null;
let trailPolyline = null;
let trailCoords = [];
let waypointMarkers = [];
let waypointPolyline = null;

// Default starting point (e.g., somewhere in Indonesia or specific lake)
const defaultLat = -7.9215169;
const defaultLng = 112.5973649;

onMounted(() => {
  // Initialize Leaflet Map
  map = L.map(mapContainer.value, {
    center: [vessel.lat || defaultLat, vessel.lng || defaultLng],
    zoom: 18,
    zoomControl: false, // We'll add our own custom controls
    attributionControl: false
  });

  // Base Layers
  const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 20,
    attribution: 'Tiles &copy; Esri'
  });

  const darkGrid = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 20,
    attribution: '&copy; CARTO'
  });

  satellite.addTo(map); // Default to satellite

  // Custom ASV Icon (Sleek Monohull / Speedboat Shape)
  const asvIcon = L.divIcon({
    className: 'asv-custom-marker',
    html: `<div class="asv-icon-wrapper drop-shadow-2xl">
             <svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
               <!-- Glowing Water Wake (Jejak Air) -->
               <path d="M 30 80 L 70 80 L 50 100 Z" fill="#ef4444" opacity="0.8"/>
               
               <!-- Sleek Boat Hull (Bodi Kapal Melengkung) -->
               <path d="M50 5 C 85 20, 80 50, 80 80 L 20 80 C 20 50, 15 20, 50 5 Z" fill="#0f172a" stroke="#ef4444" stroke-width="4" stroke-linejoin="round" />
               
               <!-- Cockpit / Cabin Deck -->
               <path d="M 35 40 Q 50 30 65 40 L 70 65 L 30 65 Z" fill="#1e293b" stroke="#ef4444" stroke-width="2" />
               
               <!-- Radar / GPS Dome (Kuning) -->
               <circle cx="50" cy="55" r="6" fill="#facc15" />
               
               <!-- Front Bow Line (Garis Haluan) -->
               <line x1="50" y1="5" x2="50" y2="35" stroke="#ef4444" stroke-width="2" opacity="0.6" />
             </svg>
           </div>`,
    iconSize: [48, 48],
    iconAnchor: [24, 24]
  });

  asvMarker = L.marker([vessel.lat || defaultLat, vessel.lng || defaultLng], { icon: asvIcon, zIndexOffset: 1000 }).addTo(map);

  // Trail Polyline
  trailPolyline = L.polyline([], {
    color: '#ef4444',
    weight: 3,
    opacity: 0.7,
    dashArray: '5, 10',
    lineJoin: 'round'
  }).addTo(map);

  // Waypoints Polyline
  waypointPolyline = L.polyline([], {
    color: '#facc15', // Yellow warning color for planning
    weight: 3,
    opacity: 0.8
  }).addTo(map);

  // Map Click Event for Waypoints
  map.on('click', (e) => {
    // Add waypoint to Pinia store
    mission.addWaypoint(e.latlng.lat, e.latlng.lng);
    renderWaypoints();
  });
});

// Watch ASV position to update marker and trail
watch(() => [vessel.lat, vessel.lng, vessel.heading], ([lat, lng, heading]) => {
  if (!map || !asvMarker) return;
  if (lat === 0 && lng === 0) return; // Ignore initial empty coords

  const newPos = [lat, lng];

  // Update Marker Position
  asvMarker.setLatLng(newPos);

  // Rotate the marker using CSS inside the divIcon wrapper
  const el = asvMarker.getElement();
  if (el) {
    const wrapper = el.querySelector('.asv-icon-wrapper');
    if (wrapper) {
      wrapper.style.transform = `rotate(${heading}deg)`;
      // Removed CSS transition so it behaves exactly like CompassRose (no 360 glitch)
    }
  }

  // Update Trail
  trailCoords.push(newPos);
  if (trailCoords.length > 10000) trailCoords.shift(); // Keep last 10000 points (~15 mins at 10Hz)
  trailPolyline.setLatLngs(trailCoords);

  // Auto-pan if map is tracking (could add a toggle state for this)
  // map.panTo(newPos);
}, { deep: true });

// --- GEO-TAG FORMATTING & TIME ---
const currentTime = ref(new Date());
let timeInterval = null;

const formatDDMMMM = (deg, isLat) => {
  const absolute = Math.abs(deg);
  const degrees = Math.floor(absolute);
  // Format minutes to 4 decimal places and replace dot with comma as requested
  const minutes = ((absolute - degrees) * 60).toFixed(4).replace('.', ',');
  const dir = isLat ? (deg >= 0 ? 'N' : 'S') : (deg >= 0 ? 'E' : 'W');
  return `[${degrees.toString().padStart(isLat ? 2 : 3, '0')} ${minutes} ${dir}]`;
};

const formattedDate = computed(() => {
  return currentTime.value.toLocaleDateString('en-GB', { weekday: 'short', year: 'numeric', month: 'short', day: '2-digit' }).toUpperCase();
});
const formattedTime = computed(() => {
  return currentTime.value.toLocaleTimeString('en-GB', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
});

// --- MOCK SIMULATION FOR DEMO ---
let simInterval = null;
const startSimulation = () => {
  if (simInterval) return;
  console.log("Starting ASV movement simulation...");
  vessel.isSimulating = true;

  // Sync initial position if it's way off
  if (Math.abs(vessel.lat - defaultLat) > 2) {
    vessel.lat = defaultLat;
    vessel.lng = defaultLng;
  }

  if (vessel.heading === 0) {
    vessel.heading = 45; // Start pointing North-East
  }

  simInterval = setInterval(() => {
    // Move forward slightly
    const speed = 0.00002; // Approx 22cm per tick (2.2m per sec)

    // Convert heading to radians for math
    const headingRad = (vessel.heading - 90) * (Math.PI / 180);

    vessel.lat += Math.sin(headingRad) * -speed;
    vessel.lng += Math.cos(headingRad) * speed;

    // Slightly turn right continuously
    // vessel.heading += 0.5;
    // if (vessel.heading >= 360) vessel.heading = 0;
    // Normalize heading to -180 .. 180
    // if (vessel.heading > 180) {
    //   vessel.heading -= 360;
    // } else if (vessel.heading < -180) {
    //   vessel.heading += 360;
    // }

  }, 100); // 10Hz update
};

const stopSimulation = () => {
  vessel.isSimulating = false;
  if (simInterval) clearInterval(simInterval);
  simInterval = null;
};
// --------------------------------

// Render Waypoints based on Mission Store
const renderWaypoints = () => {
  if (!map) return;

  // Clear existing markers
  waypointMarkers.forEach(m => map.removeLayer(m));
  waypointMarkers = [];

  const coords = mission.waypoints.map(wp => [wp.lat, wp.lng]);
  waypointPolyline.setLatLngs(coords);

  mission.waypoints.forEach((wp, index) => {
    const wpIcon = L.divIcon({
      className: 'wp-custom-marker',
      html: `<div class="w-6 h-6 bg-warning text-black font-black text-[10px] rounded-full flex items-center justify-center border-2 border-black shadow-lg">
               ${index + 1}
             </div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    });

    const m = L.marker([wp.lat, wp.lng], { icon: wpIcon }).addTo(map);
    m.on('contextmenu', () => {
      // Right click to remove waypoint
      mission.removeWaypoint(index);
      renderWaypoints();
    });
    waypointMarkers.push(m);
  });
};

// Re-render if store changes from external component
watch(() => mission.waypoints.length, () => {
  renderWaypoints();
});

onMounted(() => {
  timeInterval = setInterval(() => currentTime.value = new Date(), 1000);
});

watch(() => props.visibleLayers, (layers) => {
  if (!map) return;

  // Toggle Vessel Marker
  if (layers.includes('vessel') && !map.hasLayer(asvMarker)) {
    asvMarker.addTo(map);
  } else if (!layers.includes('vessel') && map.hasLayer(asvMarker)) {
    map.removeLayer(asvMarker);
  }

  // Toggle Trail
  if (layers.includes('trail') && !map.hasLayer(trailPolyline)) {
    trailPolyline.addTo(map);
  } else if (!layers.includes('trail') && map.hasLayer(trailPolyline)) {
    map.removeLayer(trailPolyline);
  }
}, { deep: true });

onUnmounted(() => {
  if (timeInterval) clearInterval(timeInterval);
  stopSimulation();
  if (map) {
    map.remove();
    map = null;
  }
});
</script>

<template>
  <div
    class="relative w-full h-full bg-background rounded-xl overflow-hidden shadow-2xl border border-(--border-subtle)">
    <!-- Leaflet Map Container -->
    <div ref="mapContainer" class="w-full h-full z-0 cursor-crosshair"></div>

    <!-- DEV: Simulation Toggle -->
    <div class="absolute top-6 left-1/2 -translate-x-1/2 z-10 flex gap-2">
      <button @click="simInterval ? stopSimulation() : startSimulation()"
        class="px-4 py-2 rounded-full font-black text-xs uppercase shadow-xl transition-all"
        :class="simInterval ? 'bg-danger text-white' : 'bg-primary text-black'">
        {{ simInterval ? '🛑 Stop Demo' : '▶️ Play Movement Demo' }}
      </button>
    </div>

    <!-- Map Controls Overlay -->
    <div class="absolute bottom-6 right-6 flex flex-col gap-3 z-10">
      <button @click="map && map.setZoom(map.getZoom() + 1)"
        class="w-12 h-12 bg-card/90 backdrop-blur-md text-(--text-primary) rounded-xl border border-(--border-subtle) hover:bg-primary hover:text-black transition-all shadow-xl font-bold text-xl flex items-center justify-center">+</button>
      <button @click="map && map.setZoom(map.getZoom() - 1)"
        class="w-12 h-12 bg-card/90 backdrop-blur-md text-(--text-primary) rounded-xl border border-(--border-subtle) hover:bg-primary hover:text-black transition-all shadow-xl font-bold text-xl flex items-center justify-center">-</button>

      <button @click="map && map.panTo([vessel.lat || defaultLat, vessel.lng || defaultLng])"
        class="mt-4 w-12 h-12 bg-primary/20 backdrop-blur-md text-primary rounded-xl border border-primary hover:bg-primary hover:text-black transition-all shadow-xl flex items-center justify-center"
        title="Center to ASV">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </button>
    </div>

    <!-- Geo-Tag & Telemetry Overlay -->
    <div class="absolute top-6 left-6 z-10 flex flex-col gap-3 pointer-events-none">
      
      <!-- Live Status & Geo-Tag Time -->
      <div class="bg-card/90 backdrop-blur-md border border-(--border-subtle) px-4 py-3 rounded-xl shadow-2xl flex items-center gap-4">
        <div class="relative flex h-3 w-3">
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-success opacity-75"></span>
          <span class="relative inline-flex rounded-full h-3 w-3 bg-success"></span>
        </div>
        <div class="flex flex-col">
          <span class="text-[10px] font-black text-white/50 uppercase tracking-widest leading-none mb-1">Live Geo-Tag</span>
          <div class="flex items-center gap-2 font-mono text-xs font-bold text-white leading-none">
            <span class="text-primary">{{ formattedDate }}</span>
            <span class="text-(--text-secondary)">|</span>
            <span>{{ formattedTime }} <span class="text-white/50 text-[10px]">WIB</span></span>
          </div>
        </div>
      </div>

      <!-- Advanced Coordinates Box -->
      <div class="bg-card/90 backdrop-blur-md border border-(--border-subtle) p-4 rounded-xl shadow-2xl flex flex-col gap-3">
        <div class="flex justify-between gap-6 items-center border-b border-white/5 pb-2">
          <span class="text-[10px] text-(--text-secondary) uppercase font-bold tracking-widest">ASV LAT</span>
          <span class="text-[12px] font-mono text-primary font-bold">{{ formatDDMMMM(vessel.lat, true) }}</span>
        </div>
        <div class="flex justify-between gap-6 items-center">
          <span class="text-[10px] text-(--text-secondary) uppercase font-bold tracking-widest">ASV LNG</span>
          <span class="text-[12px] font-mono text-primary font-bold">{{ formatDDMMMM(vessel.lng, false) }}</span>
        </div>
      </div>

      <!-- SOG & COG (Speed & Course) -->
      <div class="flex gap-3">
        <div class="flex-1 bg-card/90 backdrop-blur-md border border-(--border-subtle) p-3 rounded-xl shadow-2xl flex flex-col">
          <span class="text-[9px] text-(--text-secondary) uppercase font-black tracking-widest mb-1">SOG (Knots)</span>
          <span class="text-lg font-mono text-white font-bold leading-none">{{ vessel.sog.toFixed(1) }}</span>
        </div>
        <div class="flex-1 bg-card/90 backdrop-blur-md border border-(--border-subtle) p-3 rounded-xl shadow-2xl flex flex-col">
          <span class="text-[9px] text-(--text-secondary) uppercase font-black tracking-widest mb-1">COG (Deg)</span>
          <span class="text-lg font-mono text-white font-bold leading-none">{{ vessel.cog.toFixed(1) }}°</span>
        </div>
        <div class="flex-1 bg-card/90 backdrop-blur-md border border-(--border-subtle) p-3 rounded-xl shadow-2xl flex flex-col">
          <span class="text-[9px] text-(--text-secondary) uppercase font-black tracking-widest mb-1">HDG (Deg)</span>
          <span class="text-lg font-mono text-primary font-bold leading-none">{{ vessel.heading.toFixed(1) }}°</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
/* Leaflet Global Overrides */
.leaflet-container {
  background: #0f172a !important;
  /* Tailwind slate-900 */
  font-family: inherit;
}

.asv-icon-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
