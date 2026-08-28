<script setup>
/**
 * Panel "Position and Mission Imaging Infos" — seluruh field geo-tag yang diminta
 * lembar ketentuan, dalam satu tempat yang enak dibaca (dan di-screenshot) juri.
 *
 * Formatnya diambil dari @/utils/geotag, yang merupakan cerminan persis dari
 * flightcontrolAsv1/camera/geotag.py — jadi angka di layar ini dan geo-tag yang
 * tercetak pada foto hasil TAKE_IMAGE selalu memakai format yang sama.
 *
 * Jam/tanggal memakai waktu LOKAL komputer base station, bukan waktu kapal: kapal
 * tidak mengirimkan jamnya, dan foto misi diberi cap waktu lokal perangkat kapal.
 * Selama keduanya diset zona waktu yang sama (WIB), keduanya konsisten.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { MapPin } from 'lucide-vue-next';
import { useVesselStore } from '@/stores/vesselStore';
import { formatDay, formatDate, formatTime, formatCoordA, formatCoordB } from '@/utils/geotag';

const vessel = useVesselStore();

const now = ref(new Date());
let timer = null;
onMounted(() => { timer = setInterval(() => { now.value = new Date(); }, 1000); });
onUnmounted(() => { if (timer) clearInterval(timer); });

// Tanpa fix GPS, lat/lng masih berisi koordinat default — menampilkannya sebagai
// posisi kapal itu menyesatkan, apalagi di panel yang dipakai menilai.
const hasFix = computed(() => vessel.isGpsValid && (vessel.lat !== 0 || vessel.lng !== 0));

const rows = computed(() => [
  { label: 'DAY', value: formatDay(now.value) },
  { label: 'DATE', value: formatDate(now.value) },
  { label: 'TIME', value: formatTime(now.value), suffix: 'WIB' },
  {
    label: 'SOG',
    value: `${vessel.sog.toFixed(2)} knot`,
    suffix: `${vessel.sogKmh.toFixed(2)} km/h`,
  },
  {
    label: 'COG',
    value: vessel.cogValid ? `${vessel.cog.toFixed(2)}°` : '—',
    suffix: vessel.cogValid ? 'deg' : 'kapal terlalu pelan',
  },
]);

const coords = computed(() => [
  { label: 'COORDINATE — FORMAT A (DEGREE, DECIMAL)', value: hasFix.value ? formatCoordA(vessel.lat, vessel.lng) : '—' },
  { label: 'COORDINATE — FORMAT B (DEGREE, MINUTE)', value: hasFix.value ? formatCoordB(vessel.lat, vessel.lng) : '—' },
]);
</script>

<template>
  <div class="glass-card p-5 space-y-4">
    <div class="flex items-center justify-between">
      <span class="text-xs font-bold uppercase tracking-widest text-(--text-primary) flex items-center gap-1.5">
        <MapPin class="w-4 h-4 text-primary" />
        Position &amp; Mission Imaging Infos
      </span>
      <span v-if="!hasFix" class="text-[9px] px-2 py-0.5 rounded bg-warning/10 text-warning font-bold">
        MENUNGGU FIX GPS
      </span>
    </div>

    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
      <div v-for="r in rows" :key="r.label"
        class="bg-(--bg-secondary) border border-(--border-subtle) rounded-lg p-3">
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest block mb-1">
          {{ r.label }}
        </span>
        <span class="font-mono text-lg font-bold text-(--text-primary) leading-none">{{ r.value }}</span>
        <span v-if="r.suffix" class="block text-[10px] text-(--text-secondary) font-bold uppercase mt-1">
          {{ r.suffix }}
        </span>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div v-for="c in coords" :key="c.label"
        class="bg-(--bg-secondary) border border-(--border-subtle) rounded-lg p-3">
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest block mb-1">
          {{ c.label }}
        </span>
        <span class="font-mono text-base font-bold text-primary break-all">{{ c.value }}</span>
      </div>
    </div>
  </div>
</template>
