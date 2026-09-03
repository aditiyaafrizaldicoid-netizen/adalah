<script setup>
/**
 * Panel lintasan — ringkasan perekaman jalur kapal.
 *
 * Panel ini SENGAJA tidak menyimpan apa pun sendiri. Seluruh angkanya dibaca dari
 * trajectoryStore, yang merekam di latar belakang lepas dari halaman mana yang
 * sedang dibuka. Kalau panel ini yang menyimpan datanya, menutup halaman akan
 * menghentikan perekaman — persis kekeliruan yang membuat versi sebelumnya
 * kehilangan seluruh lintasan setiap kali operator berpindah halaman.
 */
import { computed } from "vue";
import {
  Route, Play, Pause, Crosshair, Eye, EyeOff, Trash2, Satellite, AlertTriangle,
} from "lucide-vue-next";
import { useTrajectoryStore } from "@/stores/trajectoryStore";
import { useVesselStore } from "@/stores/vesselStore";
import { useWebsocketStore } from "@/stores/websocketStore";

const traj = useTrajectoryStore();
const vessel = useVesselStore();
const ws = useWebsocketStore();

const NAMA_FIX = { 0: "TANPA FIX", 1: "TANPA FIX", 2: "2D", 3: "3D", 4: "DGPS", 5: "RTK", 6: "RTK" };

const labelFix = computed(() => NAMA_FIX[vessel.gpsFix] || `FIX ${vessel.gpsFix}`);
const fixLayak = computed(() => vessel.gpsFix >= 2);

/** Merekam = tombol menyala DAN telemetri benar-benar sampai DAN fix layak. */
const sedangMerekam = computed(
  () => traj.merekam && ws.status === "CONNECTED" && fixLayak.value
);

const alasanDiam = computed(() => {
  if (!traj.merekam) return "Perekaman dijeda operator";
  if (ws.status !== "CONNECTED") return "Telemetri terputus";
  if (!fixLayak.value) return "GPS belum terkunci — titik tidak direkam";
  return "";
});

const jarak = computed(() => {
  const m = traj.jarakTotalM;
  return m >= 1000 ? `${(m / 1000).toFixed(2)} km` : `${m.toFixed(0)} m`;
});

const durasi = computed(() => {
  const d = Math.max(0, Math.floor(traj.durasiMs / 1000));
  const j = Math.floor(d / 3600);
  const m = Math.floor((d % 3600) / 60);
  const dt = d % 60;
  const dua = (n) => String(n).padStart(2, "0");
  return j > 0 ? `${j}:${dua(m)}:${dua(dt)}` : `${dua(m)}:${dua(dt)}`;
});

const totalDitolak = computed(
  () => traj.tolakFix + traj.tolakLompatan + traj.tolakFcPutus
);

function konfirmasiHapus() {
  // Lintasan yang sudah dihapus tidak bisa dikembalikan, dan tombolnya bersebelahan
  // dengan tombol yang dipakai sepanjang lomba.
  if (window.confirm("Hapus seluruh lintasan yang sudah terekam?")) {
    traj.bersihkan();
  }
}
</script>

<template>
  <div class="bg-card border border-(--border-subtle) rounded-xl p-4 space-y-3">
    <!-- Judul + status -->
    <div class="flex items-center justify-between">
      <h3 class="text-sm font-black text-(--text-primary) uppercase tracking-widest flex items-center gap-2">
        <Route class="w-4 h-4 text-primary" />
        Lintasan
      </h3>
      <span class="flex items-center gap-1.5 text-[9px] font-bold px-2 py-0.5 rounded"
        :class="sedangMerekam ? 'bg-emerald-500/10 text-emerald-400' : 'bg-(--bg-secondary) text-(--text-muted)'">
        <span class="w-1.5 h-1.5 rounded-full"
          :class="sedangMerekam ? 'bg-emerald-400 animate-pulse' : 'bg-(--text-muted)'"></span>
        {{ sedangMerekam ? 'MEREKAM' : 'DIAM' }}
      </span>
    </div>

    <p v-if="alasanDiam" class="flex items-start gap-1.5 text-[10px] text-warning">
      <AlertTriangle class="w-3 h-3 shrink-0 mt-px" />
      <span>{{ alasanDiam }}</span>
    </p>

    <!-- Angka utama -->
    <div class="grid grid-cols-2 gap-2">
      <div class="bg-(--bg-secondary) rounded-lg px-3 py-2">
        <div class="text-[9px] text-(--text-muted) font-bold uppercase tracking-wider">Jarak Tempuh</div>
        <div class="text-lg font-mono font-black text-(--text-primary)">{{ jarak }}</div>
      </div>
      <div class="bg-(--bg-secondary) rounded-lg px-3 py-2">
        <div class="text-[9px] text-(--text-muted) font-bold uppercase tracking-wider">Durasi</div>
        <div class="text-lg font-mono font-black text-(--text-primary)">{{ durasi }}</div>
      </div>
    </div>

    <div class="flex items-center justify-between text-[10px] font-mono text-(--text-secondary)">
      <span>{{ traj.jumlahTitik.toLocaleString('id-ID') }} titik</span>
      <span>{{ traj.jumlahSegmen }} segmen</span>
      <span class="flex items-center gap-1" :class="fixLayak ? '' : 'text-warning'">
        <Satellite class="w-3 h-3" />
        {{ labelFix }} · {{ vessel.satellites }} sat
      </span>
    </div>

    <!-- Keterangan warna -->
    <div class="flex items-center gap-4 text-[10px] text-(--text-secondary) pt-1">
      <span class="flex items-center gap-1.5">
        <span class="w-5 h-0.5 rounded" style="background: #22d3ee"></span> Misi otonom
      </span>
      <span class="flex items-center gap-1.5">
        <span class="w-5 h-0.5 rounded"
          style="background: repeating-linear-gradient(90deg,#f59e0b 0 4px,transparent 4px 7px)"></span>
        Kendali manual
      </span>
    </div>

    <!-- Kendali -->
    <div class="grid grid-cols-2 gap-2 pt-1">
      <button type="button" @click="traj.merekam = !traj.merekam"
        class="flex items-center justify-center gap-1.5 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider border transition-colors"
        :class="traj.merekam
          ? 'bg-(--bg-secondary) border-(--border-subtle) text-(--text-secondary) hover:text-warning'
          : 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400'">
        <component :is="traj.merekam ? Pause : Play" class="w-3.5 h-3.5" />
        {{ traj.merekam ? 'Jeda' : 'Lanjutkan' }}
      </button>

      <button type="button" @click="traj.mengikutiKapal = !traj.mengikutiKapal"
        class="flex items-center justify-center gap-1.5 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider border transition-colors"
        :class="traj.mengikutiKapal
          ? 'bg-primary/10 border-primary/40 text-primary'
          : 'bg-(--bg-secondary) border-(--border-subtle) text-(--text-secondary)'">
        <Crosshair class="w-3.5 h-3.5" /> Ikuti Kapal
      </button>

      <button type="button" @click="traj.tampilkan = !traj.tampilkan"
        class="flex items-center justify-center gap-1.5 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider border transition-colors bg-(--bg-secondary) border-(--border-subtle) text-(--text-secondary) hover:text-primary">
        <component :is="traj.tampilkan ? Eye : EyeOff" class="w-3.5 h-3.5" />
        {{ traj.tampilkan ? 'Tampil' : 'Disembunyikan' }}
      </button>

      <button type="button" @click="konfirmasiHapus()"
        class="flex items-center justify-center gap-1.5 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider border transition-colors bg-(--bg-secondary) border-(--border-subtle) text-(--text-secondary) hover:text-danger hover:border-danger/40">
        <Trash2 class="w-3.5 h-3.5" /> Hapus
      </button>
    </div>

    <!-- Diagnostik: kenapa ada telemetri yang TIDAK jadi titik -->
    <details v-if="totalDitolak > 0" class="text-[10px] text-(--text-muted)">
      <summary class="cursor-pointer hover:text-(--text-secondary)">
        {{ totalDitolak.toLocaleString('id-ID') }} pembacaan tidak direkam
      </summary>
      <ul class="mt-1.5 space-y-0.5 pl-3">
        <li v-if="traj.tolakFix">GPS belum terkunci: {{ traj.tolakFix.toLocaleString('id-ID') }}</li>
        <li v-if="traj.tolakLompatan">Lompatan mustahil (glitch GPS): {{ traj.tolakLompatan.toLocaleString('id-ID') }}</li>
        <li v-if="traj.tolakFcPutus">Flight controller putus: {{ traj.tolakFcPutus.toLocaleString('id-ID') }}</li>
        <li v-if="traj.titikDibuang">Titik terlama dibuang (batas memori): {{ traj.titikDibuang.toLocaleString('id-ID') }}</li>
      </ul>
    </details>
  </div>
</template>
