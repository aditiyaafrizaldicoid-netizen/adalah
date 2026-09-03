<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue';
import { useVesselStore } from '@/stores/vesselStore';
import { useMissionStore } from '@/stores/missionStore';
import { useGeofenceStore } from '@/stores/geofenceStore';
import { useArenaStore } from '@/stores/arenaStore';
import { useTrajectoryStore } from '@/stores/trajectoryStore';
import { useTrajectoryLayer } from '@/composables/useTrajectoryLayer';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { formatDay, formatDate, formatTime, formatCoordA, formatCoordB } from '@/utils/geotag';

const props = defineProps({
  width: { type: Number, default: 800 },
  height: { type: Number, default: 600 },
  visibleLayers: { type: Array, default: () => ['grid', 'vessel', 'trail', 'buoys'] },
  // 'waypoint' | 'arena' | 'geofence' | 'none'
  mapMode: { type: String, default: 'waypoint' },
});

const vessel = useVesselStore();
const mission = useMissionStore();
const arenaStore = useArenaStore();
const geofence = useGeofenceStore();
const traj = useTrajectoryStore();
const trajLayer = useTrajectoryLayer();

const mapContainer = ref(null);
let map = null;
let asvMarker = null;
// Jejak kapal TIDAK lagi ditumpuk di komponen ini. Dulu koordinatnya hidup di
// variabel milik instance ini, jadi berpindah halaman menghapus seluruh lintasan,
// dan selama peta tidak terbuka tidak ada satu titik pun yang terekam. Sekarang
// datanya ada di trajectoryStore (hidup selama aplikasi hidup) dan digambar oleh
// useTrajectoryLayer, sehingga Mapping dan Juri melihat lintasan yang sama persis.
let waypointMarkers = [];
let waypointPolyline = null;

// Arena layers
let arenaLayers = [];        // all active arena Leaflet layers
let draftTrailPolyline = null; // preview polyline while drawing trail

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

  // Lintasan kapal — datanya dari trajectoryStore, sudah berisi titik yang
  // terekam SEBELUM peta ini dibuka.
  trajLayer.pasang(map);
  trajLayer.setTampil(props.visibleLayers.includes('trail'));

  // Waypoints Polyline
  waypointPolyline = L.polyline([], {
    color: '#facc15', // Yellow warning color for planning
    weight: 3,
    opacity: 0.8
  }).addTo(map);

  // Draft trail preview polyline
  draftTrailPolyline = L.polyline([], {
    color: '#60a5fa',
    weight: 2,
    dashArray: '6, 6',
    opacity: 0.7,
  }).addTo(map);

  // Map Click Event — routed by mapMode prop
  map.on('click', (e) => {
    if (props.mapMode === 'arena') {
      arenaStore.placeElement(e.latlng.lat, e.latlng.lng);
    } else if (props.mapMode === 'waypoint') {
      mission.addWaypoint(e.latlng.lat, e.latlng.lng);
      renderWaypoints();
    } else if (props.mapMode === 'geofence') {
      geofence.setCenter(e.latlng.lat, e.latlng.lng);
    }
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

  // Peta hanya digeser saat penanda kapal HAMPIR keluar dari bidang pandang,
  // bukan tiap kali posisi berubah: memaksa kapal selalu di tengah membuat peta
  // merebut kembali tampilan tiap kali operator menggesernya untuk melihat area lain.
  if (traj.mengikutiKapal && !map.getBounds().pad(-0.15).contains(newPos)) {
    map.panTo(newPos, { animate: true, duration: 0.5 });
  }
});

// --- GEO-TAG FORMATTING & TIME ---
const currentTime = ref(new Date());
let timeInterval = null;

// Format tanggal/jam/koordinat memakai util bersama (@/utils/geotag) yang merupakan
// cerminan dari camera/geotag.py di kapal — supaya yang terbaca di peta ini persis
// sama dengan geo-tag yang tercetak pada foto hasil TAKE_IMAGE.
//
// Formatter lokal sebelumnya menghasilkan '[07 55,2910 N]' (huruf arah di BELAKANG,
// tanpa simbol ° dan '), dan tanggal 'MON, 25 AUG 2026' — keduanya tidak sesuai
// contoh di lembar ketentuan.
const formattedDate = computed(() =>
  `${formatDay(currentTime.value)} ${formatDate(currentTime.value)}`);
const formattedTime = computed(() => formatTime(currentTime.value));

// Tanpa fix GPS, lat/lng masih berisi koordinat default — jangan dipampang sebagai
// posisi kapal di panel yang dipakai menilai.
const hasFix = computed(() => vessel.isGpsValid && (vessel.lat !== 0 || vessel.lng !== 0));
const coordA = computed(() => hasFix.value ? formatCoordA(vessel.lat, vessel.lng) : '—');
const coordB = computed(() => hasFix.value ? formatCoordB(vessel.lat, vessel.lng) : '—');

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
      // Right click to remove waypoint — hanya di mode waypoint. Tanpa penjagaan
      // ini, peta baca-saja (mapMode="none", dipakai Panel Juri) masih bisa
      // menghapus waypoint lewat klik kanan.
      if (props.mapMode !== 'waypoint') return;
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

// ── Arena Rendering ─────────────────────────────────────────────────────────
function makeIcon(color, letter) {
  return L.divIcon({
    className: '',
    html: `<div style="width:22px;height:22px;border-radius:50%;background:${color};border:2.5px solid white;
                box-shadow:0 2px 6px rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;
                font-size:9px;font-weight:900;color:white;line-height:1">${letter}</div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

const BUOY_ICONS = {
  red:   makeIcon('#ef4444', 'M'),
  green: makeIcon('#22c55e', 'H'),
};

const TRAIL_COLORS = {
  green: '#22c55e',
  blue:  '#3b82f6',
};

function renderArena() {
  if (!map) return;

  // Remove existing arena layers
  arenaLayers.forEach((l) => map.removeLayer(l));
  arenaLayers = [];

  const { buoys, trails } = arenaStore.activeArena;

  // Render buoys
  buoys.forEach((b) => {
    const icon = BUOY_ICONS[b.type] || BUOY_ICONS.green;
    const m = L.marker([b.lat, b.lng], { icon })
      .bindTooltip(b.label, { permanent: false, direction: 'top', offset: [0, -14] })
      .addTo(map);
    m.on('contextmenu', () => {
      arenaStore.removeBuoy(b.id);
    });
    arenaLayers.push(m);
  });

  // Render completed trails
  trails.forEach((t) => {
    if (!t.points || t.points.length < 2) return;
    const coords = t.points.map((p) => [p.lat, p.lng]);
    const line = L.polyline(coords, {
      color: TRAIL_COLORS[t.type] || '#22c55e',
      weight: 3,
      opacity: 0.85,
    })
      .bindTooltip(t.label, { permanent: false, direction: 'center' })
      .addTo(map);
    line.on('contextmenu', () => {
      arenaStore.removeTrail(t.id);
    });
    arenaLayers.push(line);

    // Start/end markers for trail
    const startIcon = L.divIcon({
      className: '',
      html: `<div style="width:10px;height:10px;border-radius:50%;background:${TRAIL_COLORS[t.type] || '#22c55e'};border:2px solid white;box-shadow:0 1px 4px rgba(0,0,0,0.5)"></div>`,
      iconSize: [10, 10], iconAnchor: [5, 5],
    });
    arenaLayers.push(L.marker(coords[0], { icon: startIcon, interactive: false }).addTo(map));
    arenaLayers.push(L.marker(coords[coords.length - 1], { icon: startIcon, interactive: false }).addTo(map));
  });
}

// Draft trail preview
watch(() => [...arenaStore.activeTrailPoints], (pts) => {
  if (!draftTrailPolyline) return;
  const color = arenaStore.activePlaceTool === 'trail_blue' ? '#3b82f6' : '#22c55e';
  draftTrailPolyline.setStyle({ color });
  draftTrailPolyline.setLatLngs(pts.map((p) => [p.lat, p.lng]));
}, { deep: true });

// Re-render arena when buoys/trails change
watch(
  () => [arenaStore.activeArena.buoys.length, arenaStore.activeArena.trails.length],
  () => renderArena()
);
watch(() => arenaStore.activeArena.id, () => renderArena());

// ── Geofence ────────────────────────────────────────────────────────────────
// DUA lingkaran digambar sekaligus, dan itu disengaja:
//   - garis TEBAL  = batas yang benar-benar berlaku di kapal (dari telemetri)
//   - garis PUTUS  = batas yang sedang digambar operator tapi BELUM disimpan
// Tanpa membedakan keduanya, operator tidak punya cara melihat bahwa lingkaran
// yang baru dia geser belum sampai ke kapal — dan batas yang dikira aktif padahal
// belum itu memberi rasa aman palsu.
let geofenceAktifLayer = null;
let geofenceDraftLayer = null;

const renderGeofence = () => {
  if (!map) return;
  if (geofenceAktifLayer) { map.removeLayer(geofenceAktifLayer); geofenceAktifLayer = null; }
  if (geofenceDraftLayer) { map.removeLayer(geofenceDraftLayer); geofenceDraftLayer = null; }

  const aktif = geofence.aktifDiKapal;
  if (aktif.enabled && aktif.radius_m > 0 && (aktif.lat || aktif.lon)) {
    geofenceAktifLayer = L.circle([aktif.lat, aktif.lon], {
      radius: aktif.radius_m,
      color: '#f97316', weight: 2, fillColor: '#f97316', fillOpacity: 0.06,
    }).addTo(map).bindTooltip(`Geofence aktif — ${aktif.radius_m.toFixed(0)} m`);
  }

  const d = geofence.draft;
  if (geofence.punyaPusat && Number(d.radius_m) > 0 && geofence.belumTersimpan) {
    geofenceDraftLayer = L.circle([d.lat, d.lon], {
      radius: Number(d.radius_m),
      color: '#38bdf8', weight: 2, dashArray: '6, 6',
      fillColor: '#38bdf8', fillOpacity: 0.04,
    }).addTo(map).bindTooltip(`Belum disimpan — ${Number(d.radius_m).toFixed(0)} m`);
  }
};

watch(
  () => [
    geofence.draft.lat, geofence.draft.lon, geofence.draft.radius_m,
    geofence.draft.enabled, geofence.belumTersimpan,
    geofence.aktifDiKapal.enabled, geofence.aktifDiKapal.radius_m,
    geofence.aktifDiKapal.lat, geofence.aktifDiKapal.lon,
  ],
  renderGeofence
);
onMounted(renderGeofence);

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

  // Toggle Lintasan
  trajLayer.setTampil(layers.includes('trail'));
}, { deep: true });

onUnmounted(() => {
  if (timeInterval) clearInterval(timeInterval);
  // Layer dilepas SEBELUM peta dibuang. Perekaman di store tetap berjalan —
  // yang berhenti hanyalah penggambarannya.
  trajLayer.lepas();
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
        <div class="flex flex-col gap-1 border-b border-white/5 pb-2">
          <span class="text-[9px] text-(--text-secondary) uppercase font-bold tracking-widest">Koordinat — Format A</span>
          <span class="text-[12px] font-mono text-primary font-bold">{{ coordA }}</span>
        </div>
        <div class="flex flex-col gap-1">
          <span class="text-[9px] text-(--text-secondary) uppercase font-bold tracking-widest">Koordinat — Format B</span>
          <span class="text-[12px] font-mono text-primary font-bold">{{ coordB }}</span>
        </div>
      </div>

      <!-- SOG & COG (Speed & Course) -->
      <div class="flex gap-3">
        <div class="flex-1 bg-card/90 backdrop-blur-md border border-(--border-subtle) p-3 rounded-xl shadow-2xl flex flex-col">
          <span class="text-[9px] text-(--text-secondary) uppercase font-black tracking-widest mb-1">SOG</span>
          <span class="text-lg font-mono text-white font-bold leading-none">{{ vessel.sog.toFixed(2) }}<span class="text-[10px] text-white/50 font-normal"> kn</span></span>
          <span class="text-[10px] font-mono text-white/60 font-bold leading-none mt-1">{{ vessel.sogKmh.toFixed(2) }} km/h</span>
        </div>
        <div class="flex-1 bg-card/90 backdrop-blur-md border border-(--border-subtle) p-3 rounded-xl shadow-2xl flex flex-col">
          <span class="text-[9px] text-(--text-secondary) uppercase font-black tracking-widest mb-1">COG (Deg)</span>
          <span class="text-lg font-mono text-white font-bold leading-none">{{ vessel.cogValid ? vessel.cog.toFixed(1) + '°' : '—' }}</span>
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
