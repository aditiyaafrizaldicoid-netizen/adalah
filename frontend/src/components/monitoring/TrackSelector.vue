<script setup>
/**
 * Pemilih lintasan arena — A atau B.
 *
 * Tombol yang tersorot SELALU lintasan yang benar-benar berlaku di kapal, bukan
 * yang baru diklik. Kapal boleh menolak (mis. selagi misi berjalan), dan tombol
 * yang pindah sendiri akan menampilkan setelan yang sebenarnya tidak berlaku.
 *
 * Tabel sisinya ditampilkan lengkap, bukan cuma huruf A/B: operator bisa
 * mencocokkannya langsung dengan arena di depan mata sebelum kapal diturunkan —
 * memilih lintasan yang keliru membalik arah setiap koreksi kemudi.
 */
import { computed } from "vue";
import { Route, Loader2, AlertTriangle, CheckCircle2 } from "lucide-vue-next";
import { useTrackStore, LINTASAN } from "@/stores/trackStore";
import { useWebsocketStore } from "@/stores/websocketStore";
import { useMissionStore } from "@/stores/missionStore";

const track = useTrackStore();
const ws = useWebsocketStore();
const mission = useMissionStore();

const misiJalan = computed(() => mission.missionStatus === "RUNNING");

const BARIS = [
  { kunci: "green", label: "Bola hijau", warna: "bg-emerald-400" },
  { kunci: "red", label: "Bola merah", warna: "bg-red-400" },
  { kunci: "blue_box", label: "Box biru", warna: "bg-sky-400" },
  { kunci: "green_box", label: "Box hijau", warna: "bg-lime-400" },
];

/** Sisi yang akan berlaku kalau tombol ini dipilih — untuk pratinjau. */
const sisi = (nama) => LINTASAN[nama].sisi;
</script>

<template>
  <div class="glass-card p-4 space-y-3 border-t-4 border-t-primary">
    <div class="flex items-center justify-between">
      <h3 class="text-sm font-black text-(--text-primary) uppercase tracking-widest flex items-center gap-2">
        <Route class="w-4 h-4 text-primary" />
        Lintasan Arena
      </h3>
      <span class="text-[9px] font-bold px-2 py-0.5 rounded"
        :class="ws.status === 'CONNECTED'
          ? 'bg-primary/10 text-primary' : 'bg-(--bg-secondary) text-(--text-muted)'">
        {{ ws.status === 'CONNECTED' ? `AKTIF: ${track.aktif}` : 'KAPAL OFFLINE' }}
      </span>
    </div>

    <!-- Sakelar A / B -->
    <div class="grid grid-cols-2 gap-2">
      <button v-for="nama in ['A', 'B']" :key="nama" type="button"
        @click="track.pilih(nama)"
        :disabled="track.mengirim || misiJalan"
        class="relative py-3 rounded-xl border text-xs font-black uppercase tracking-widest transition-all disabled:cursor-not-allowed"
        :class="track.aktif === nama
          ? 'bg-primary/15 border-primary text-primary'
          : 'bg-(--bg-secondary) border-(--border-subtle) text-(--text-secondary) hover:border-primary/40 disabled:opacity-40'">
        <Loader2 v-if="track.menunggu === nama" class="w-3.5 h-3.5 animate-spin absolute left-3 top-1/2 -translate-y-1/2" />
        Lintasan {{ nama }}
        <span v-if="nama === 'B'" class="block text-[8px] font-bold opacity-60 tracking-normal">bawaan</span>
      </button>
    </div>

    <p v-if="misiJalan" class="flex items-start gap-1.5 text-[10px] text-warning">
      <AlertTriangle class="w-3 h-3 shrink-0 mt-px" />
      <span>
        Misi sedang berjalan — lintasan dikunci. Membalik konvensi sisi di tengah
        misi membalik arah setiap koreksi kemudi seketika.
      </span>
    </p>

    <!-- Tabel sisi yang berlaku: dicocokkan langsung dengan arena -->
    <div class="bg-(--bg-secondary) rounded-lg p-2.5 space-y-1">
      <div class="text-[9px] font-bold text-(--text-muted) uppercase tracking-wider mb-1">
        Sisi lintasan (dilihat dari haluan)
      </div>
      <div v-for="b in BARIS" :key="b.kunci"
        class="flex items-center justify-between text-[11px]">
        <span class="flex items-center gap-1.5 text-(--text-secondary)">
          <span class="w-2 h-2 rounded-full" :class="b.warna"></span>{{ b.label }}
        </span>
        <span class="font-mono font-bold text-(--text-primary) uppercase">
          {{ track.sisiAktif[b.kunci] }}
        </span>
      </div>
    </div>

    <p v-if="track.pesan"
      class="flex items-start gap-1.5 text-[10px]"
      :class="track.pesanGagal ? 'text-warning' : 'text-(--text-secondary)'">
      <component :is="track.pesanGagal ? AlertTriangle : CheckCircle2"
        class="w-3 h-3 shrink-0 mt-px" />
      <span>{{ track.pesan }}</span>
    </p>
  </div>
</template>
