<script setup>
/**
 * Panel Juri — konsol baca-saja, tanpa login.
 *
 * Sengaja TIDAK memakai MainLayout: Sidebar mengarah ke halaman operator dan
 * Topbar memuat KILL SWITCH. Panel ini berdiri sendiri supaya tidak ada satu pun
 * kontrol yang bisa tersentuh dari sini.
 *
 * Semua data mengalir satu arah dari WebSocket (TELEMETRY / MISSION_STATUS /
 * WARNING) yang sudah dibuka App.vue. Halaman ini tidak pernah memanggil
 * wsStore.sendCommand(), tidak menulis ke store, dan tidak mengirim POST/PUT.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import {
  Activity,
  Navigation,
  Compass,
  Battery,
  Trophy,
  Wifi,
  WifiOff,
  Sun,
  Moon,
  Eye,
  ShieldAlert,
  AlertTriangle,
  Gauge,
  Satellite,
  Info,
} from "lucide-vue-next";
import { useVesselStore } from "@/stores/vesselStore";
import { useMissionStore } from "@/stores/missionStore";
import { useScoringStore } from "@/stores/scoringStore";
import { useWebsocketStore } from "@/stores/websocketStore";
import { useThemeStore } from "@/stores/themeStore";
import { formatTime } from "@/utils/geotag";
import { VIDEO_STREAM_URL } from "@/config/api";

import MetricCard from "@/components/ui/MetricCard.vue";
import ProgressBar from "@/components/ui/ProgressBar.vue";
import GeotagPanel from "@/components/monitoring/GeotagPanel.vue";
import GridMap from "@/components/mapping/GridMap.vue";
import MjpegImg from "@/components/monitoring/MjpegImg.vue";

const vessel = useVesselStore();
const mission = useMissionStore();
const scoring = useScoringStore();
const wsStore = useWebsocketStore();
const themeStore = useThemeStore();

const streamUrl = VIDEO_STREAM_URL;

const isDark = computed(() => themeStore.theme === "dark");

// Jam dinding base station, sama formatnya dengan GeotagPanel.
const now = ref(formatTime(new Date()));
let clockTimer = null;
onMounted(() => {
  clockTimer = setInterval(() => { now.value = formatTime(new Date()); }, 1000);
});
onUnmounted(() => { if (clockTimer) clearInterval(clockTimer); });

// mission.elapsedSec dihitung lokal di tiap browser, bukan dikirim kapal. Kalau
// panel ini dibuka saat run SUDAH berjalan, jamnya mulai dari nol dan tidak
// mencerminkan durasi sebenarnya — juri harus tahu itu, bukan menebak.
const joinedMidRun = ref(mission.missionStatus === "RUNNING");
watch(
  () => mission.missionStatus,
  (status, prev) => {
    if (status === "RUNNING" && prev !== "RUNNING" && prev !== undefined) {
      // Transisi ke RUNNING terlihat dari panel ini, jadi jamnya ikut dari awal.
      joinedMidRun.value = false;
    }
    if (status === "IDLE") joinedMidRun.value = false;
  }
);

const wsOnline = computed(() => wsStore.status === "CONNECTED");

const statusPills = computed(() => [
  {
    label: "MISI",
    value: mission.missionStatus,
    tone: mission.missionStatus === "RUNNING" ? "warning" : "muted",
  },
  {
    label: "ARM",
    value: vessel.isArmed ? "ARMED" : "DISARMED",
    tone: vessel.isArmed ? "danger" : "muted",
  },
  {
    label: "MODE",
    value: vessel.mode,
    tone: "muted",
  },
  {
    label: "GPS",
    value: `FIX ${vessel.gpsFix} · ${vessel.satellites} SAT`,
    tone: vessel.isGpsValid ? "success" : "danger",
  },
]);

// Baris telemetri detail — murni tampilan, tidak ada yang bisa diklik.
const navRows = computed(() => [
  { label: "Cross Track Error", value: `${vessel.xte.toFixed(2)} m` },
  { label: "Distance to Waypoint", value: `${vessel.dtw.toFixed(2)} m` },
  { label: "Next Waypoint", value: `#${vessel.nextWp}` },
  { label: "Pitch", value: `${vessel.pitch.toFixed(2)}°` },
  { label: "Roll", value: `${vessel.roll.toFixed(2)}°` },
  { label: "Yaw", value: `${vessel.yaw.toFixed(2)}°` },
]);

const engineRows = computed(() => [
  { label: "Thruster Kiri", value: `${vessel.thrusterL.toFixed(0)} %` },
  { label: "Thruster Kanan", value: `${vessel.thrusterR.toFixed(0)} %` },
  { label: "RPM Kiri", value: `${vessel.rpmL.toFixed(0)}` },
  { label: "RPM Kanan", value: `${vessel.rpmR.toFixed(0)}` },
  { label: "Baterai", value: `${vessel.batteryPct.toFixed(0)} % · ${vessel.batteryVolt.toFixed(2)} V` },
  { label: "Sinyal", value: `${vessel.signalStrength} %` },
]);

// Komponen skor yang DIHITUNG dari telemetri — ikut hidup di panel ini.
const liveScoreRows = computed(() => [
  { label: "NM", desc: "Buoy gate terlewati", value: scoring.nm.toFixed(0) },
  { label: "Buoy Pass", desc: "Hitungan mentah dari kapal", value: String(mission.buoyPassCount) },
  { label: "NT", desc: "Durasi run (detik)", value: scoring.nt.toFixed(0) },
]);

// Komponen skor yang diketik juri/operator di halaman Scoring. Nilainya hidup di
// browser operator saja — tidak pernah lewat WebSocket — jadi di panel ini selalu
// nol. Ditampilkan apa adanya dengan penanda, bukan disembunyikan.
const manualScoreRows = computed(() => [
  { label: "IMH", desc: "Image quality surface", value: scoring.imh.toFixed(0) },
  { label: "IMB", desc: "Image quality underwater", value: scoring.imb.toFixed(0) },
  { label: "DC", desc: "Docking balls", value: scoring.dc.toFixed(0) },
  { label: "P", desc: "Penalti", value: scoring.p.toFixed(0) },
]);
</script>

<template>
  <div class="h-screen w-screen flex flex-col bg-background overflow-hidden">
    <!-- ── Header ───────────────────────────────────────────────────────── -->
    <header
      class="h-16 shrink-0 bg-(--bg-topbar) border-b border-(--border-primary) flex items-center justify-between px-6 gap-4"
    >
      <div class="flex items-center gap-4 min-w-0">
        <div class="flex items-center gap-3 shrink-0">
          <div class="w-9 h-9 bg-(--accent-primary) rounded-lg flex items-center justify-center">
            <Activity class="text-white w-5 h-5" />
          </div>
          <div class="leading-tight">
            <div class="font-bold text-lg tracking-tight text-(--text-primary)">
              UMM<span class="text-(--accent-primary)"> STATION</span>
            </div>
            <div class="text-[9px] font-bold uppercase tracking-[0.25em] text-(--text-muted)">
              Panel Juri
            </div>
          </div>
        </div>

        <span
          class="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-(--border-subtle) bg-(--bg-secondary) text-[10px] font-black uppercase tracking-widest text-(--text-secondary)"
        >
          <Eye class="w-3.5 h-3.5 text-primary" />
          Read Only
        </span>
      </div>

      <div class="flex items-center gap-3">
        <div
          :class="[
            'flex items-center gap-1.5 text-[10px] font-bold px-3 py-1.5 rounded-full border',
            wsOnline
              ? 'bg-success/10 text-success border-success/30'
              : 'bg-danger/10 text-danger border-danger/30',
          ]"
        >
          <component :is="wsOnline ? Wifi : WifiOff" class="w-3.5 h-3.5" />
          {{ wsStore.status }}
        </div>

        <span class="text-sm font-mono font-bold text-(--text-primary) tabular-nums">
          {{ now }}
        </span>

        <button
          type="button"
          @click="themeStore.toggleTheme()"
          class="p-2 rounded-lg border border-(--border-primary) bg-(--bg-card) text-(--text-secondary) hover:text-(--accent-primary) transition-all active:scale-95"
          :title="isDark ? 'Mode terang' : 'Mode gelap'"
        >
          <Sun v-if="isDark" class="w-4 h-4" />
          <Moon v-else class="w-4 h-4" />
        </button>
      </div>
    </header>

    <!-- ── Isi ──────────────────────────────────────────────────────────── -->
    <main class="flex-1 overflow-y-auto p-6 space-y-6">
      <!-- Status ringkas -->
      <div class="flex flex-wrap items-center gap-2">
        <div
          v-for="pill in statusPills"
          :key="pill.label"
          :class="[
            'flex items-center gap-2 px-3 py-1.5 rounded-full border text-[10px] font-bold uppercase tracking-widest',
            pill.tone === 'danger'
              ? 'bg-danger/10 text-danger border-danger/30'
              : pill.tone === 'success'
              ? 'bg-success/10 text-success border-success/30'
              : pill.tone === 'warning'
              ? 'bg-warning/10 text-warning border-warning/30'
              : 'bg-(--bg-secondary) text-(--text-secondary) border-(--border-subtle)',
          ]"
        >
          <span class="opacity-60">{{ pill.label }}</span>
          <span>{{ pill.value }}</span>
        </div>
      </div>

      <!-- Telemetri utama -->
      <div class="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <MetricCard
          label="Speed Over Ground"
          :value="vessel.sog.toFixed(2)"
          unit="Knots"
          :icon="Activity"
          color="primary"
          :note="`${vessel.sogKmh.toFixed(2)} km/h`"
        />
        <MetricCard
          label="Course Over Ground"
          :value="vessel.cogValid ? vessel.cog.toFixed(2) : '—'"
          unit="Deg"
          :icon="Compass"
          color="success"
          :note="vessel.cogValid ? '' : 'kapal terlalu pelan'"
        />
        <MetricCard
          label="Heading"
          :value="vessel.heading.toFixed(2)"
          unit="Deg"
          :icon="Navigation"
          color="warning"
        />
        <MetricCard
          label="Battery"
          :value="vessel.batteryVolt.toFixed(2)"
          unit="V"
          :icon="Battery"
          :color="vessel.batteryVolt > 22 ? 'success' : 'danger'"
        />
        <MetricCard
          label="Buoy Gate"
          :value="String(mission.buoyPassCount)"
          unit="Pass"
          :icon="Trophy"
          color="primary"
        />
      </div>

      <div class="grid grid-cols-12 gap-6">
        <!-- Progres misi -->
        <div class="col-span-12 lg:col-span-7 glass-card p-5 border-l-4 border-l-primary">
          <div class="flex justify-between items-center mb-4">
            <span class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest">
              Progres Misi
            </span>
            <span class="text-primary font-mono font-bold">{{ mission.formattedTime }}</span>
          </div>

          <div class="space-y-3">
            <div class="flex justify-between items-end">
              <span class="text-sm font-semibold text-(--text-primary)">
                {{ mission.activeStepLabel }}
              </span>
              <span class="text-xs text-(--text-secondary)">
                {{ mission.progressPct }}% · langkah
                {{ mission.totalSteps ? mission.currentStepIdx + 1 : 0 }}/{{ mission.totalSteps }}
              </span>
            </div>
            <ProgressBar :progress="mission.progressPct" color="primary" />
          </div>

          <p
            v-if="joinedMidRun"
            class="mt-4 flex items-start gap-2 text-[10px] leading-relaxed text-warning"
          >
            <AlertTriangle class="w-3.5 h-3.5 shrink-0 mt-px" />
            Panel dibuka saat run sudah berjalan. Jam misi dihitung sejak panel ini
            terbuka, bukan sejak start — durasi di atas lebih pendek dari sebenarnya.
          </p>
        </div>

        <!-- Skor -->
        <div class="col-span-12 lg:col-span-5 glass-card p-5">
          <div class="flex justify-between items-center mb-4">
            <span class="text-xs font-bold text-(--text-secondary) uppercase tracking-widest">
              Komponen Skor
            </span>
            <span class="text-2xl font-black text-primary font-mono tracking-tighter">
              {{ (isFinite(scoring.totalScore) ? scoring.totalScore : 0).toFixed(2) }}
            </span>
          </div>

          <div class="space-y-1.5">
            <div
              v-for="row in liveScoreRows"
              :key="row.label"
              class="flex items-center justify-between gap-3 py-1.5 border-b border-(--border-subtle) last:border-0"
            >
              <div class="min-w-0">
                <span class="text-xs font-bold text-(--text-primary)">{{ row.label }}</span>
                <span class="block text-[10px] text-(--text-muted) truncate">{{ row.desc }}</span>
              </div>
              <span class="font-mono font-bold text-sm text-(--text-primary) shrink-0">
                {{ row.value }}
              </span>
            </div>
          </div>

          <div class="mt-4 pt-3 border-t border-(--border-primary)">
            <div class="flex items-center gap-1.5 mb-2">
              <Info class="w-3 h-3 text-(--text-muted)" />
              <span class="text-[9px] font-bold uppercase tracking-widest text-(--text-muted)">
                Input manual · tidak tersinkron
              </span>
            </div>
            <div class="grid grid-cols-2 gap-x-4 gap-y-1">
              <div
                v-for="row in manualScoreRows"
                :key="row.label"
                class="flex items-center justify-between gap-2 py-1"
              >
                <span class="text-[11px] text-(--text-secondary)" :title="row.desc">
                  {{ row.label }}
                </span>
                <span class="font-mono text-xs text-(--text-muted)">{{ row.value }}</span>
              </div>
            </div>
            <p class="mt-2 text-[10px] leading-relaxed text-(--text-muted)">
              IMH, IMB, DC, dan P diketik di halaman Scoring operator dan tidak dikirim
              lewat WebSocket, jadi di panel ini selalu nol. Skor di atas hanya
              mencerminkan bagian yang dihitung dari telemetri.
            </p>
          </div>
        </div>
      </div>

      <!-- Geo-tag: field yang diminta lembar ketentuan -->
      <GeotagPanel />

      <!-- Peta & video -->
      <div class="grid grid-cols-12 gap-6">
        <div class="col-span-12 lg:col-span-7 glass-card overflow-hidden min-h-[420px] relative">
          <!-- mapMode="none": klik peta tidak menambah waypoint dan tidak menempatkan
               elemen arena. Tombol zoom/pan bawaan tetap ada karena hanya menggeser
               sudut pandang, tidak mengubah data apa pun. -->
          <GridMap
            :height="420"
            map-mode="none"
            :visible-layers="['grid', 'vessel', 'trail', 'buoys']"
          />
        </div>

        <div class="col-span-12 lg:col-span-5 glass-card overflow-hidden flex flex-col">
          <div
            class="px-4 py-2.5 border-b border-(--border-primary) flex items-center justify-between"
          >
            <span class="text-[10px] font-black uppercase tracking-widest text-(--text-secondary)">
              FPV Cam
            </span>
            <span
              :class="[
                'text-[9px] font-black uppercase tracking-widest px-2 py-0.5 rounded-full',
                vessel.cameraConnected
                  ? 'bg-success/10 text-success'
                  : 'bg-danger/10 text-danger',
              ]"
            >
              {{ vessel.cameraConnected ? "Live" : "No Signal" }}
            </span>
          </div>
          <!-- MjpegImg dipakai langsung, bukan VideoCard: VideoCard punya tombol
               start/stop recording dan streaming yang mengubah state kapal. -->
          <div class="flex-1 bg-black aspect-video">
            <MjpegImg :src="streamUrl" placeholder="Stream tidak tersedia" />
          </div>
        </div>
      </div>

      <!-- Detail telemetri & peringatan -->
      <div class="grid grid-cols-12 gap-6">
        <div class="col-span-12 lg:col-span-4 glass-card p-5">
          <div class="flex items-center gap-2 mb-4">
            <Navigation class="w-4 h-4 text-primary" />
            <span class="text-xs font-bold uppercase tracking-widest text-(--text-primary)">
              Navigasi
            </span>
          </div>
          <div class="space-y-1">
            <div
              v-for="row in navRows"
              :key="row.label"
              class="flex items-center justify-between gap-3 py-1.5 border-b border-(--border-subtle) last:border-0"
            >
              <span class="text-[11px] text-(--text-secondary)">{{ row.label }}</span>
              <span class="font-mono text-xs font-bold text-(--text-primary)">{{ row.value }}</span>
            </div>
          </div>
        </div>

        <div class="col-span-12 lg:col-span-4 glass-card p-5">
          <div class="flex items-center gap-2 mb-4">
            <Gauge class="w-4 h-4 text-primary" />
            <span class="text-xs font-bold uppercase tracking-widest text-(--text-primary)">
              Penggerak & Daya
            </span>
          </div>
          <div class="space-y-1">
            <div
              v-for="row in engineRows"
              :key="row.label"
              class="flex items-center justify-between gap-3 py-1.5 border-b border-(--border-subtle) last:border-0"
            >
              <span class="text-[11px] text-(--text-secondary)">{{ row.label }}</span>
              <span class="font-mono text-xs font-bold text-(--text-primary)">{{ row.value }}</span>
            </div>
          </div>
        </div>

        <div class="col-span-12 lg:col-span-4 glass-card p-5 border-t-4 border-t-danger">
          <div class="flex items-center gap-2 mb-4">
            <ShieldAlert class="w-4 h-4 text-danger" />
            <span class="text-xs font-bold uppercase tracking-widest text-(--text-primary)">
              Peringatan Sistem
            </span>
            <span
              v-if="vessel.warnings.length"
              class="ml-auto bg-danger text-white text-[9px] font-black px-2 py-0.5 rounded-full"
            >
              {{ vessel.warnings.length }}
            </span>
          </div>

          <!-- Tanpa tombol dismiss: juri melihat, tidak membersihkan. -->
          <div class="space-y-2 max-h-[220px] overflow-y-auto">
            <div
              v-for="w in vessel.warnings"
              :key="w.id"
              :class="[
                'p-2.5 rounded-lg border',
                w.level === 'critical'
                  ? 'bg-danger/10 border-danger/20'
                  : w.level === 'warning'
                  ? 'bg-warning/10 border-warning/20'
                  : 'bg-primary/10 border-primary/20',
              ]"
            >
              <span
                :class="[
                  'text-[9px] font-black uppercase tracking-wider block mb-1',
                  w.level === 'critical'
                    ? 'text-danger'
                    : w.level === 'warning'
                    ? 'text-warning'
                    : 'text-primary',
                ]"
              >
                {{ w.level === "critical" ? "Kritis" : w.level === "warning" ? "Warning" : "Info" }}
                <span class="opacity-50 ml-1">{{ w.code }}</span>
              </span>
              <p class="text-[10px] text-(--text-primary) leading-relaxed">{{ w.message }}</p>
            </div>

            <div
              v-if="!vessel.warnings.length && vessel.isConnected && wsOnline"
              class="p-3 bg-success/10 border border-success/20 rounded-lg"
            >
              <span class="text-[10px] font-bold text-success uppercase">OK</span>
              <p class="text-xs text-(--text-primary) mt-1">Semua sistem nominal</p>
            </div>

            <div
              v-if="!vessel.isConnected"
              class="p-3 bg-danger/10 border border-danger/20 rounded-lg"
            >
              <span class="text-[10px] font-bold text-danger uppercase">Critical</span>
              <p class="text-xs text-(--text-primary) mt-1">Flight Controller tidak terhubung</p>
            </div>

            <div v-if="!wsOnline" class="p-3 bg-warning/10 border border-warning/20 rounded-lg">
              <span class="text-[10px] font-bold text-warning uppercase">Warning</span>
              <p class="text-xs text-(--text-primary) mt-1">WebSocket terputus dari backend</p>
            </div>
          </div>
        </div>
      </div>
    </main>

    <!-- ── Footer ───────────────────────────────────────────────────────── -->
    <footer
      class="h-8 shrink-0 border-t border-(--border-primary) bg-(--bg-topbar) flex items-center justify-between px-6 text-[10px] uppercase tracking-widest font-bold text-(--text-muted)"
    >
      <span class="flex items-center gap-2">
        <Satellite class="w-3 h-3" />
        {{ vessel.satellites }} sat · fix {{ vessel.gpsFix }}
      </span>
      <span>Base Station ASV · Universitas Muhammadiyah Malang</span>
    </footer>
  </div>
</template>
