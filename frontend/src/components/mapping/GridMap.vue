<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue';
import { useVesselStore } from '@/stores/vesselStore';
import { useMissionStore } from '@/stores/missionStore';
import { useGeofenceStore } from '@/stores/geofenceStore';
import { useArenaStore } from '@/stores/arenaStore';
import { useTrajectoryStore } from '@/stores/trajectoryStore';
import { useTrajectoryLayer } from '@/composables/useTrajectoryLayer';
import 'mapbox-gl/dist/mapbox-gl.css';
import mapboxgl from 'mapbox-gl';
import { MAPBOX_TOKEN, GAYA_BAWAAN } from '@/config/mapbox';
import { kotakGeoJSON, koleksiKosong } from '@/utils/geo';
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
/**
 * Gaya peta dimuat ASINKRON. addSource/addLayer sebelum itu selesai akan
 * melempar "Style is not done loading", sementara watcher store bisa menyala
 * kapan saja — termasuk sebelum peta siap. Satu bendera ini yang menjaganya.
 */
let petaSiap = false;
let asvMarker = null;
let asvTampil = true;
// Jejak kapal TIDAK lagi ditumpuk di komponen ini. Dulu koordinatnya hidup di
// variabel milik instance ini, jadi berpindah halaman menghapus seluruh lintasan,
// dan selama peta tidak terbuka tidak ada satu titik pun yang terekam. Sekarang
// datanya ada di trajectoryStore (hidup selama aplikasi hidup) dan digambar oleh
// useTrajectoryLayer, sehingga Mapping dan Juri melihat lintasan yang sama persis.
let waypointMarkers = [];
let arenaMarkers = [];
let popupHover = [];

// Default starting point (e.g., somewhere in Indonesia or specific lake)
const defaultLat = -7.9215169;
const defaultLng = 112.5973649;

// ── Sumber & layer ──────────────────────────────────────────────────────────
// Mapbox GL tidak punya objek gambar seperti L.polyline/L.circle yang bisa
// ditambah-buang satu per satu. Yang ada: SOURCE (data GeoJSON) dan LAYER (cara
// menggambarnya). Jadi semuanya dibuat SEKALI di sini, lalu isinya diganti
// dengan setData — bukan layer-nya yang dibongkar pasang tiap kali data berubah.
const SRC = {
  waypointGaris: 'waypoint-garis',
  draftTrail: 'draft-trail',
  arenaTrail: 'arena-trail',
  arenaTrailUjung: 'arena-trail-ujung',
  geofenceAktif: 'geofence-aktif',
  geofenceDraft: 'geofence-draft',
};

/** Ganti isi sebuah source, aman dipanggil sebelum peta siap. */
function tulisSource(id, data) {
  if (!map || !petaSiap) return;
  const src = map.getSource(id);
  if (src) src.setData(data);
}

/** Buat elemen DOM untuk penanda dari potongan HTML. */
function elemenDari(html) {
  const kotak = document.createElement('div');
  kotak.innerHTML = html.trim();
  return kotak.firstElementChild;
}

/**
 * Tooltip melayang saat kursor menyentuh sebuah layer.
 *
 * Pengganti bindTooltip milik Leaflet, yang tidak ada padanannya di Mapbox GL:
 * Popup di sini harus dipasang dan dilepas sendiri lewat kejadian mouse.
 */
function pasangTooltipLayer(idLayer, ambilTeks) {
  const popup = new mapboxgl.Popup({
    closeButton: false,
    closeOnClick: false,
    className: 'peta-tooltip',
  });
  popupHover.push(popup);

  map.on('mousemove', idLayer, (e) => {
    const teks = e.features?.length ? ambilTeks(e.features[0]) : '';
    if (!teks) return;
    popup.setLngLat(e.lngLat).setText(teks).addTo(map);
  });
  map.on('mouseleave', idLayer, () => popup.remove());
}

/** Tooltip untuk penanda DOM (pelampung), yang bukan bagian dari layer. */
function pasangTooltipElemen(el, lngLat, teks) {
  const popup = new mapboxgl.Popup({
    closeButton: false,
    closeOnClick: false,
    offset: 14,
    className: 'peta-tooltip',
  });
  popupHover.push(popup);
  el.addEventListener('mouseenter', () => popup.setLngLat(lngLat).setText(teks).addTo(map));
  el.addEventListener('mouseleave', () => popup.remove());
  return popup;
}

/**
 * Tanpa token, Mapbox MELEMPAR saat peta dibuat — bukan sekadar gagal memuat
 * tile. Lemparan di dalam onMounted mematikan seluruh pohon komponen: Dashboard
 * dan Panel Juri ikut kosong, padahal telemetri, kamera FPV, dan tombol misi di
 * halaman yang sama tidak ada hubungannya dengan peta. Maka peta yang tidak bisa
 * hidup harus GAGAL SENDIRIAN, dan mengatakan apa yang kurang.
 */
const tokenAda = !!MAPBOX_TOKEN;

onMounted(() => {
  if (!tokenAda) return;
  mapboxgl.accessToken = MAPBOX_TOKEN;

  map = new mapboxgl.Map({
    container: mapContainer.value,
    style: GAYA_BAWAAN,
    center: [vessel.lng || defaultLng, vessel.lat || defaultLat], // [lng, lat] — kebalikan Leaflet
    zoom: 17, // zoom Mapbox satu tingkat lebih "dekat" dari Leaflet pada skala yang sama
    attributionControl: false, // dipasang ulang di bawah dalam bentuk ringkas
  });

  // Atribusi WAJIB ADA — syarat layanan Mapbox, bukan pilihan gaya. Bentuk
  // ringkas ("i" kecil) dipakai supaya tidak menutupi panel telemetri, dan
  // ditaruh di kiri-bawah agar tidak bertumpuk dengan tombol zoom di kanan-bawah.
  map.addControl(new mapboxgl.AttributionControl({ compact: true }), 'bottom-left');

  // Custom ASV Icon (Sleek Monohull / Speedboat Shape)
  const asvEl = elemenDari(`<div class="asv-icon-wrapper drop-shadow-2xl">
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
           </div>`);

  asvMarker = new mapboxgl.Marker({
    element: asvEl,
    // Haluan kapal adalah arah SEBENARNYA di bumi, jadi ikonnya ikut berputar
    // bersama peta saat operator memutar sudut pandang. Dengan 'viewport' ikon
    // akan tetap menunjuk ke atas layar dan menunjukkan haluan yang salah.
    rotationAlignment: 'map',
  })
    .setLngLat([vessel.lng || defaultLng, vessel.lat || defaultLat])
    .setRotation(vessel.heading || 0)
    .addTo(map);

  // Map Click Event — routed by mapMode prop
  map.on('click', (e) => {
    if (props.mapMode === 'arena') {
      arenaStore.placeElement(e.lngLat.lat, e.lngLat.lng);
    } else if (props.mapMode === 'waypoint') {
      mission.addWaypoint(e.lngLat.lat, e.lngLat.lng);
      renderWaypoints();
    } else if (props.mapMode === 'geofence') {
      geofence.setCenter(e.lngLat.lat, e.lngLat.lng);
    }
  });

  map.on('load', () => {
    petaSiap = true;

    for (const id of Object.values(SRC)) {
      map.addSource(id, { type: 'geojson', data: koleksiKosong() });
    }

    // Urutan penambahan = urutan tumpukan. Isi geofence paling bawah supaya
    // tidak menutupi apa pun; lintasan kapal ditambahkan paling akhir (oleh
    // trajLayer.pasang) supaya bukti gerak kapal tidak pernah tertimbun.
    map.addLayer({
      id: 'geofence-aktif-isi', type: 'fill', source: SRC.geofenceAktif,
      paint: { 'fill-color': '#f97316', 'fill-opacity': 0.06 },
    });
    map.addLayer({
      id: 'geofence-aktif-garis', type: 'line', source: SRC.geofenceAktif,
      paint: { 'line-color': '#f97316', 'line-width': 2 },
    });
    map.addLayer({
      id: 'geofence-draft-isi', type: 'fill', source: SRC.geofenceDraft,
      paint: { 'fill-color': '#38bdf8', 'fill-opacity': 0.04 },
    });
    map.addLayer({
      id: 'geofence-draft-garis', type: 'line', source: SRC.geofenceDraft,
      // [3,3] pada tebal 2 = 6 px putus / 6 px kosong, sama seperti
      // dashArray "6, 6" milik Leaflet. Satuannya kelipatan tebal garis.
      paint: { 'line-color': '#38bdf8', 'line-width': 2, 'line-dasharray': [3, 3] },
    });

    map.addLayer({
      id: 'arena-trail-layer', type: 'line', source: SRC.arenaTrail,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: { 'line-color': ['get', 'warna'], 'line-width': 3, 'line-opacity': 0.85 },
    });
    map.addLayer({
      id: 'arena-trail-ujung-layer', type: 'circle', source: SRC.arenaTrailUjung,
      paint: {
        'circle-radius': 5,
        'circle-color': ['get', 'warna'],
        'circle-stroke-width': 2,
        'circle-stroke-color': '#ffffff',
      },
    });

    map.addLayer({
      id: 'waypoint-garis-layer', type: 'line', source: SRC.waypointGaris,
      layout: { 'line-join': 'round', 'line-cap': 'round' },
      paint: {
        'line-color': '#facc15', // Yellow warning color for planning
        'line-width': 3,
        'line-opacity': 0.8,
      },
    });
    map.addLayer({
      id: 'draft-trail-layer', type: 'line', source: SRC.draftTrail,
      paint: {
        'line-color': '#60a5fa', 'line-width': 2,
        'line-dasharray': [3, 3], 'line-opacity': 0.7,
      },
    });

    pasangTooltipLayer('arena-trail-layer', (f) => f.properties.label);
    pasangTooltipLayer('geofence-aktif-garis', (f) => f.properties.label);
    pasangTooltipLayer('geofence-draft-garis', (f) => f.properties.label);

    // Right click to remove trail — hanya di mode arena, sejalan dengan
    // penjagaan yang sama pada waypoint dan pelampung.
    map.on('contextmenu', 'arena-trail-layer', (e) => {
      if (props.mapMode !== 'arena') return;
      arenaStore.removeTrail(e.features[0].properties.id);
    });

    // Lintasan kapal — datanya dari trajectoryStore, sudah berisi titik yang
    // terekam SEBELUM peta ini dibuka.
    trajLayer.pasang(map);
    trajLayer.setTampil(props.visibleLayers.includes('trail'));

    renderWaypoints();
    renderArena();
    renderGeofence();
    renderDraftTrail();
  });
});

// Watch ASV position to update marker and trail
watch(() => [vessel.lat, vessel.lng, vessel.heading], ([lat, lng, heading]) => {
  if (!map || !asvMarker) return;
  if (lat === 0 && lng === 0) return; // Ignore initial empty coords

  asvMarker.setLngLat([lng, lat]);
  // Rotasi ditangani Mapbox sendiri, tidak lagi lewat transform CSS pada
  // pembungkus ikon: Mapbox memakai transform elemen penanda untuk menempatkan
  // posisinya, jadi menulisi transform yang sama akan melempar ikon ke sudut layar.
  // Tanpa transisi, persis seperti CompassRose (tidak ada glitch saat melewati 360).
  asvMarker.setRotation(heading);

  // Peta hanya digeser saat penanda kapal HAMPIR keluar dari bidang pandang,
  // bukan tiap kali posisi berubah: memaksa kapal selalu di tengah membuat peta
  // merebut kembali tampilan tiap kali operator menggesernya untuk melihat area lain.
  if (traj.mengikutiKapal && !dalamPandanganAman(lng, lat)) {
    map.panTo([lng, lat], { animate: true, duration: 500 });
  }
});

/**
 * Apakah titik masih berada di 70% bagian tengah layar?
 *
 * Pengganti `getBounds().pad(-0.15).contains()` milik Leaflet — LngLatBounds
 * Mapbox tidak punya pad(), jadi penyusutan 15% tiap sisi dihitung di sini.
 */
function dalamPandanganAman(lng, lat) {
  const b = map.getBounds();
  const lebar = b.getEast() - b.getWest();
  const tinggi = b.getNorth() - b.getSouth();
  const m = 0.15;
  return (
    lng > b.getWest() + lebar * m && lng < b.getEast() - lebar * m &&
    lat > b.getSouth() + tinggi * m && lat < b.getNorth() - tinggi * m
  );
}

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
  if (!map || !petaSiap) return;

  // Clear existing markers
  waypointMarkers.forEach((m) => m.remove());
  waypointMarkers = [];

  const coords = mission.waypoints.map((wp) => [wp.lng, wp.lat]);
  // LineString wajib punya minimal dua titik; satu waypoint menghasilkan
  // geometri tak sah yang ditolak diam-diam oleh Mapbox.
  tulisSource(SRC.waypointGaris, coords.length >= 2
    ? { type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }
    : koleksiKosong());

  mission.waypoints.forEach((wp, index) => {
    const el = elemenDari(`<div class="w-6 h-6 bg-warning text-black font-black text-[10px] rounded-full flex items-center justify-center border-2 border-black shadow-lg cursor-pointer">
               ${index + 1}
             </div>`);

    el.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      // Right click to remove waypoint — hanya di mode waypoint. Tanpa penjagaan
      // ini, peta baca-saja (mapMode="none", dipakai Panel Juri) masih bisa
      // menghapus waypoint lewat klik kanan.
      if (props.mapMode !== 'waypoint') return;
      mission.removeWaypoint(index);
      renderWaypoints();
    });

    waypointMarkers.push(new mapboxgl.Marker({ element: el }).setLngLat([wp.lng, wp.lat]).addTo(map));
  });
};

// Re-render if store changes from external component
watch(() => mission.waypoints.length, () => {
  renderWaypoints();
});

// ── Arena Rendering ─────────────────────────────────────────────────────────
const BUOY_WARNA = {
  red: '#ef4444',
  green: '#22c55e',
};
const BUOY_HURUF = {
  red: 'M',
  green: 'H',
};

const TRAIL_COLORS = {
  green: '#22c55e',
  blue:  '#3b82f6',
};

function renderArena() {
  if (!map || !petaSiap) return;

  // Remove existing arena markers
  arenaMarkers.forEach((m) => m.remove());
  arenaMarkers = [];

  const { buoys, trails } = arenaStore.activeArena;

  // Render buoys — tetap penanda DOM, bukan layer: isinya huruf dan lingkaran
  // ber-border yang jauh lebih murah ditulis sebagai HTML daripada disusun dari
  // properti circle-* Mapbox.
  buoys.forEach((b) => {
    const warna = BUOY_WARNA[b.type] || BUOY_WARNA.green;
    const huruf = BUOY_HURUF[b.type] || BUOY_HURUF.green;
    const el = elemenDari(`<div style="width:22px;height:22px;border-radius:50%;background:${warna};border:2.5px solid white;
                box-shadow:0 2px 6px rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;
                font-size:9px;font-weight:900;color:white;line-height:1;cursor:pointer">${huruf}</div>`);

    pasangTooltipElemen(el, [b.lng, b.lat], b.label);
    el.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      arenaStore.removeBuoy(b.id);
    });

    arenaMarkers.push(new mapboxgl.Marker({ element: el }).setLngLat([b.lng, b.lat]).addTo(map));
  });

  // Render completed trails
  const garis = [];
  const ujung = [];
  trails.forEach((t) => {
    if (!t.points || t.points.length < 2) return;
    const coords = t.points.map((p) => [p.lng, p.lat]);
    const warna = TRAIL_COLORS[t.type] || '#22c55e';

    garis.push({
      type: 'Feature',
      properties: { warna, label: t.label, id: t.id },
      geometry: { type: 'LineString', coordinates: coords },
    });

    // Start/end markers for trail
    for (const c of [coords[0], coords[coords.length - 1]]) {
      ujung.push({
        type: 'Feature',
        properties: { warna },
        geometry: { type: 'Point', coordinates: c },
      });
    }
  });

  tulisSource(SRC.arenaTrail, { type: 'FeatureCollection', features: garis });
  tulisSource(SRC.arenaTrailUjung, { type: 'FeatureCollection', features: ujung });
}

// Draft trail preview
function renderDraftTrail() {
  if (!map || !petaSiap) return;
  const pts = arenaStore.activeTrailPoints;
  const warna = arenaStore.activePlaceTool === 'trail_blue' ? '#3b82f6' : '#22c55e';
  map.setPaintProperty('draft-trail-layer', 'line-color', warna);
  tulisSource(SRC.draftTrail, pts.length >= 2
    ? {
        type: 'Feature', properties: {},
        geometry: { type: 'LineString', coordinates: pts.map((p) => [p.lng, p.lat]) },
      }
    : koleksiKosong());
}

watch(() => [...arenaStore.activeTrailPoints], renderDraftTrail, { deep: true });

// Re-render arena when buoys/trails change
watch(
  () => [arenaStore.activeArena.buoys.length, arenaStore.activeArena.trails.length],
  () => renderArena()
);
watch(() => arenaStore.activeArena.id, () => renderArena());

// ── Geofence ────────────────────────────────────────────────────────────────
// DUA kotak digambar sekaligus, dan itu disengaja:
//   - garis TEBAL  = batas yang benar-benar berlaku di kapal (dari telemetri)
//   - garis PUTUS  = batas yang sedang digambar operator tapi BELUM disimpan
// Tanpa membedakan keduanya, operator tidak punya cara melihat bahwa kotak
// yang baru dia ubah belum sampai ke kapal — dan batas yang dikira aktif padahal
// belum itu memberi rasa aman palsu.
//
// Ukurannya METER, dan itu sebabnya kotaknya dibuat sebagai poligon lewat
// kotakGeoJSON — yang rumusnya CERMINAN PERSIS kotak_batas() di kapal. Kotak yang
// digambar di sini dan kotak yang ditegakkan kapal adalah himpunan titik yang sama.
const ukuranSah = (g) => Number(g.lebar_m) > 0 && Number(g.tinggi_m) > 0;
const labelUkuran = (g) =>
  `${Number(g.lebar_m).toFixed(0)} × ${Number(g.tinggi_m).toFixed(0)} m`;

const renderGeofence = () => {
  if (!map || !petaSiap) return;

  const aktif = geofence.aktifDiKapal;
  if (aktif.enabled && ukuranSah(aktif) && (aktif.lat || aktif.lon)) {
    const f = kotakGeoJSON(aktif.lat, aktif.lon, aktif.lebar_m, aktif.tinggi_m);
    f.properties.label = `Geofence aktif — ${labelUkuran(aktif)}`;
    tulisSource(SRC.geofenceAktif, f);
  } else {
    tulisSource(SRC.geofenceAktif, koleksiKosong());
  }

  const d = geofence.draft;
  if (geofence.punyaPusat && ukuranSah(d) && geofence.belumTersimpan) {
    const f = kotakGeoJSON(d.lat, d.lon, Number(d.lebar_m), Number(d.tinggi_m));
    f.properties.label = `Belum disimpan — ${labelUkuran(d)}`;
    tulisSource(SRC.geofenceDraft, f);
  } else {
    tulisSource(SRC.geofenceDraft, koleksiKosong());
  }
};

watch(
  () => [
    geofence.draft.lat, geofence.draft.lon,
    geofence.draft.lebar_m, geofence.draft.tinggi_m,
    geofence.draft.enabled, geofence.belumTersimpan,
    geofence.aktifDiKapal.enabled,
    geofence.aktifDiKapal.lebar_m, geofence.aktifDiKapal.tinggi_m,
    geofence.aktifDiKapal.lat, geofence.aktifDiKapal.lon,
  ],
  renderGeofence
);

onMounted(() => {
  timeInterval = setInterval(() => currentTime.value = new Date(), 1000);
});

watch(() => props.visibleLayers, (layers) => {
  if (!map || !asvMarker) return;

  // Toggle Vessel Marker
  const mau = layers.includes('vessel');
  if (mau && !asvTampil) asvMarker.addTo(map);
  else if (!mau && asvTampil) asvMarker.remove();
  asvTampil = mau;

  // Toggle Lintasan
  trajLayer.setTampil(layers.includes('trail'));
}, { deep: true });

onUnmounted(() => {
  if (timeInterval) clearInterval(timeInterval);
  // Layer dilepas SEBELUM peta dibuang. Perekaman di store tetap berjalan —
  // yang berhenti hanyalah penggambarannya.
  trajLayer.lepas();
  popupHover.forEach((p) => p.remove());
  popupHover = [];
  waypointMarkers.forEach((m) => m.remove());
  waypointMarkers = [];
  arenaMarkers.forEach((m) => m.remove());
  arenaMarkers = [];
  if (map) {
    map.remove();
    map = null;
  }
  petaSiap = false;
});
</script>

<template>
  <div
    class="relative w-full h-full bg-background rounded-xl overflow-hidden shadow-2xl border border-(--border-subtle)">
    <!-- Mapbox GL Map Container -->
    <div ref="mapContainer" class="w-full h-full z-0"></div>

    <!-- Token belum diisi: panel lain di halaman ini tetap hidup. -->
    <div v-if="!tokenAda"
      class="absolute inset-0 z-20 flex flex-col items-center justify-center gap-3 bg-background/95 px-8 text-center">
      <span class="text-[10px] font-black uppercase tracking-widest text-danger">Peta tidak aktif</span>
      <p class="text-sm font-bold text-(--text-primary)">Token Mapbox belum diisi.</p>
      <p class="max-w-md text-xs leading-relaxed text-(--text-secondary)">
        Isi <code class="font-mono text-primary">VITE_MAPBOX_TOKEN</code> di
        <code class="font-mono text-primary">frontend/.env</code>, lalu jalankan ULANG
        <code class="font-mono text-primary">npm run dev</code> — Vite hanya membaca .env saat start.
      </p>
    </div>


    <!-- Map Controls Overlay -->
    <div class="absolute bottom-6 right-6 flex flex-col gap-3 z-10">
      <button @click="map && map.zoomIn()"
        class="w-12 h-12 bg-card/90 backdrop-blur-md text-(--text-primary) rounded-xl border border-(--border-subtle) hover:bg-primary hover:text-black transition-all shadow-xl font-bold text-xl flex items-center justify-center">+</button>
      <button @click="map && map.zoomOut()"
        class="w-12 h-12 bg-card/90 backdrop-blur-md text-(--text-primary) rounded-xl border border-(--border-subtle) hover:bg-primary hover:text-black transition-all shadow-xl font-bold text-xl flex items-center justify-center">-</button>

      <button @click="map && map.panTo([vessel.lng || defaultLng, vessel.lat || defaultLat])"
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
          <span :class="['text-lg font-mono font-bold leading-none', vessel.cogTertahanTampil ? 'text-warning' : 'text-white']">{{ vessel.cogAda ? vessel.cogTampil.toFixed(1) + '°' : '—' }}</span>
          <span v-if="vessel.cogKeterangan" class="text-[9px] font-mono text-white/50 font-bold leading-none mt-1">{{ vessel.cogKeterangan }}</span>
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
/* Mapbox GL Global Overrides */
.mapboxgl-map {
  background: #0f172a !important;
  /* Tailwind slate-900 */
  font-family: inherit;
}

/* Kursor silang dipertahankan dari versi Leaflet: peta ini dipakai MENUNJUK
   koordinat (waypoint, pusat geofence, elemen arena), bukan sekadar digeser,
   dan kursor tangan bawaan Mapbox tidak menyiratkan itu. */
.mapboxgl-canvas-container.mapboxgl-interactive {
  cursor: crosshair;
}

.asv-icon-wrapper {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Atribusi & logo dibuat samar: syarat layanan Mapbox mewajibkan keduanya
   TETAP TERBACA, jadi yang dikurangi hanya kontrasnya, bukan keberadaannya. */
.mapboxgl-ctrl-bottom-left {
  opacity: 0.55;
  transition: opacity 0.2s;
}
.mapboxgl-ctrl-bottom-left:hover {
  opacity: 1;
}

.peta-tooltip .mapboxgl-popup-content {
  background: rgba(15, 23, 42, 0.95);
  color: #e2e8f0;
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 8px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 700;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.5);
}
.peta-tooltip .mapboxgl-popup-tip {
  display: none;
}
</style>
