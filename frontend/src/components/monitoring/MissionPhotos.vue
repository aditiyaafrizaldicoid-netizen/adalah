<script setup>
/**
 * Panel foto misi — hasil step PHOTO_BOX yang dikirim kapal ke base station.
 *
 * Dua slot TETAP, selalu tampil, sesuai dua nilai yang diberi juri:
 *   - IMB / Underwater → box BIRU  (target bawah air)
 *   - IMH / Surface    → box HIJAU (target atas air)
 *
 * Box biru difoto KAMERA BAWAH AIR bila terpasang (ASV_UNDERWATER_CAMERA_INDEX di
 * .env kapal); box hijau selalu dari kamera permukaan. Kalau kamera bawah airnya
 * tidak terpasang, membeku, atau frame terakhirnya sudah basi, foto box biru tetap
 * diambil dari permukaan — dan berkasnya berakhiran "_permukaan" supaya kejatuhan
 * itu tidak pernah tersamar sebagai foto bawah air.
 *
 * Slot dibuat tetap — bukan daftar yang tumbuh — supaya operator bisa melihat sekali
 * lihat mana yang BELUM didapat. Daftar yang hanya menampilkan foto yang sudah ada
 * membuat foto yang hilang tidak terlihat sebagai masalah.
 *
 * SENGAJA TANPA loading="lazy": panel ini cuma memuat dua thumbnail, jadi lazy-load
 * tidak menghemat apa pun yang berarti — sementara ia menambah satu cara diam-diam
 * gagal (foto tidak pernah dimuat kalau deteksi viewport tidak terpicu). Foto yang
 * dinilai juri tidak boleh bergantung pada itu.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { Camera, RefreshCw, Download, ImageOff, MapPin, Waves } from "lucide-vue-next";
import { useVesselStore } from "@/stores/vesselStore";

const vessel = useVesselStore();
import { API_BASE, apiUrl } from "@/config/api";
import { useMissionStore } from "@/stores/missionStore";

const mission = useMissionStore();

const captures = ref([]);
const loading = ref(false);
const errorMsg = ref("");
const preview = ref(null); // foto yang sedang dibuka besar

// Label target dari kapal (lihat vision/class_map.py) → slot penilaian.
const SLOTS = [
  { label: "blue_box", judul: "Underwater", kode: "IMB", warna: "text-blue-400", ring: "border-blue-500/40" },
  { label: "green_box", judul: "Surface", kode: "IMH", warna: "text-emerald-400", ring: "border-emerald-500/40" },
];

/** Foto TERBARU untuk tiap slot — run berikutnya menimpa tampilan run sebelumnya. */
const bySlot = computed(() =>
  SLOTS.map((slot) => ({
    ...slot,
    foto: captures.value.find((c) => c.label === slot.label) || null,
  }))
);

/**
 * Foto yang TIDAK mengisi slot penilaian — hasil step TAKE_IMAGE.
 *
 * Backend menurunkan label dari nama berkas, dan nama berkas TAKE_IMAGE berasal
 * dari `name` step yang diketik operator ("dermaga", "foto bawah air"). Label itu
 * tidak akan pernah cocok dengan slot blue_box/green_box, jadi sebelumnya foto-
 * foto ini cuma dihitung sebagai "+N lain" dan tidak pernah digambar sama sekali.
 *
 * Akibatnya lebih buruk dari sekadar tidak terlihat: satu-satunya penanda KAMERA
 * MANA yang mengambil sebuah foto ada di lencana thumbnail. Tanpa thumbnail-nya,
 * tidak ada cara memeriksa apakah step yang diminta memakai kamera bawah air
 * benar-benar memakainya — selain masuk ke Mini PC lewat SSH dan membaca sidecar
 * JSON-nya satu per satu.
 *
 * Cadangan box biru dikecualikan: ia sudah punya tempatnya sendiri di slot
 * Underwater yang kosong (lihat cadanganBiru), dan memunculkannya dua kali
 * membuatnya terbaca seperti dua foto yang berbeda.
 */
const lainnya = computed(() =>
  captures.value.filter(
    (c) => !SLOTS.some((s) => s.label === c.label) && c.label !== "blue_box_permukaan"
  )
);

const totalLain = computed(() => lainnya.value.length);

function fullUrl(c) {
  return `${API_BASE}${c.url}`;
}

/** Kamera yang mengambil foto ini, dari sidecar JSON yang ikut dikirim backend. */
const kameraFoto = (c) => (c && c.geotag && c.geotag.kamera) || "";

/**
 * Foto box biru yang terpaksa diambil dari PERMUKAAN.
 *
 * Sengaja TIDAK mengisi slot Underwater — kalau foto bawah air tidak pernah
 * terjadi, slot itu memang harus kosong, bukan diisi foto permukaan yang
 * menyamar. Tapi keberadaannya harus dijelaskan, kalau tidak slot kosong
 * terbaca sebagai "foto gagal terkirim".
 */
const cadanganBiru = computed(
  () => captures.value.find((c) => c.label === "blue_box_permukaan") || null
);

/** Ringkasan geo-tag satu baris untuk ditempel di bawah thumbnail. */
function geoRingkas(c) {
  const g = c.geotag;
  if (!g) return null;
  // Nama field mengikuti camera/geotag.py build_fields().
  const bagian = [g.time, g.coord_a].filter(Boolean);
  if (g.sog_knot !== undefined && g.sog_knot !== null) bagian.push(`${g.sog_knot} kn`);
  return bagian.length ? bagian.join(" · ") : null;
}

async function muat() {
  loading.value = true;
  errorMsg.value = "";
  try {
    const res = await fetch(apiUrl("/api/v1/captures"));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    captures.value = Array.isArray(body.data) ? body.data : [];
  } catch (e) {
    // fetch hanya melempar saat server benar-benar tak terjangkau; status 4xx/5xx
    // lolos sebagai resolve, jadi res.ok di atas yang menangkapnya.
    errorMsg.value =
      e instanceof TypeError
        ? "Tidak dapat terhubung ke backend."
        : `Gagal memuat foto: ${e.message}`;
  } finally {
    loading.value = false;
  }
}

// Foto baru muncul saat kapal menyelesaikan satu target, jadi panel ini menyegarkan
// dirinya berkala. 10 detik: cukup cepat agar foto terlihat tak lama setelah diambil,
// cukup jarang agar tidak membebani backend yang sedang meneruskan video.
let timer = null;
onMounted(() => {
  muat();
  timer = setInterval(muat, 10_000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});

// Muat ulang SEGERA saat misi mulai berjalan. Foto run sebelumnya sudah diarsipkan
// di server tepat sebelum start (lihat missionStore._arsipkanFotoRunSebelumnya),
// dan menunggu putaran berkala berikutnya berarti operator sempat melihat slot
// yang masih terisi foto lama di detik-detik paling diperhatikan.
watch(
  () => mission.missionStatus,
  (baru, lama) => {
    if (baru === "RUNNING" && lama !== "RUNNING") muat();
  }
);

function tutupPreview() {
  preview.value = null;
}
function onKeydown(e) {
  if (e.key === "Escape") tutupPreview();
}
onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => window.removeEventListener("keydown", onKeydown));
</script>

<template>
  <div class="glass-card flex flex-col overflow-hidden">
    <!-- Header -->
    <!-- glass-card, bukan "panel": kelas .panel dan .panel-header tidak pernah
         didefinisikan di style.css mana pun, jadi panel ini selama ini tampil
         tanpa latar, tanpa border, dan tanpa padding header — termasuk di
         Dashboard. Baru terlihat saat panelnya ditaruh berdampingan dengan
         glass-card di halaman Juri. -->
    <div class="px-4 py-2.5 border-b border-(--border-primary) flex items-center justify-between">
      <div class="flex items-center gap-2">
        <Camera class="w-4 h-4 text-primary" />
        <span class="text-[11px] font-black uppercase tracking-widest text-(--text-primary)">
          Foto Misi
        </span>
        <span
          v-if="totalLain > 0"
          class="text-[9px] font-bold text-(--text-secondary) bg-card px-1.5 py-0.5 rounded"
        >
          +{{ totalLain }} lain
        </span>

        <!-- Status kamera bawah air. Ditaruh di sini, bukan di panel diagnostik:
             yang perlu tahu adalah orang yang sedang memikirkan foto box biru,
             dan waktunya adalah SEBELUM misi dijalankan. -->
        <span
          v-if="vessel.underwaterFitted"
          class="flex items-center gap-1 text-[9px] font-bold px-1.5 py-0.5 rounded"
          :class="vessel.underwaterOk
            ? 'bg-sky-500/10 text-sky-400' : 'bg-warning/10 text-warning'"
          :title="vessel.underwaterOk
            ? 'Box biru akan difoto kamera bawah air'
            : 'Kamera bawah air tidak memberi frame — box biru akan difoto dari permukaan'"
        >
          <Waves class="w-3 h-3" />
          {{ vessel.underwaterOk ? 'BAWAH AIR' : 'BAWAH AIR MATI' }}
        </span>
      </div>
      <button
        @click="muat"
        :disabled="loading"
        title="Muat ulang"
        class="p-1.5 rounded-lg text-(--text-secondary) hover:text-primary hover:bg-card transition-all disabled:opacity-40"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': loading }" />
      </button>
    </div>

    <!-- Dua slot tetap -->
    <div class="p-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
      <div
        v-for="slot in bySlot"
        :key="slot.label"
        class="rounded-xl border bg-(--bg-secondary) overflow-hidden flex flex-col"
        :class="slot.foto ? slot.ring : 'border-(--border-subtle)'"
      >
        <!-- Judul slot -->
        <div class="px-3 py-2 flex items-center justify-between border-b border-(--border-subtle)">
          <div class="flex items-baseline gap-2">
            <span class="text-[10px] font-black uppercase tracking-widest" :class="slot.warna">
              {{ slot.judul }}
            </span>
            <span class="text-[9px] font-mono text-(--text-muted)">{{ slot.kode }}</span>
            <!-- Kamera yang benar-benar mengambil foto ini. Dibaca dari sidecar,
                 bukan disimpulkan dari nama slot — slot "Underwater" adalah
                 sasaran penilaian, bukan janji tentang lensa yang dipakai. -->
            <span v-if="slot.foto && kameraFoto(slot.foto)"
              class="text-[9px] font-bold px-1.5 py-0.5 rounded"
              :class="kameraFoto(slot.foto).startsWith('bawah air')
                ? 'bg-sky-500/15 text-sky-400' : 'bg-(--bg-card) text-(--text-muted)'">
              {{ kameraFoto(slot.foto).startsWith('bawah air') ? 'BAWAH AIR' : 'PERMUKAAN' }}
            </span>
          </div>
          <a
            v-if="slot.foto"
            :href="fullUrl(slot.foto)"
            :download="slot.foto.filename"
            title="Unduh foto"
            class="p-1 rounded text-(--text-secondary) hover:text-primary transition-colors"
          >
            <Download class="w-3.5 h-3.5" />
          </a>
        </div>

        <!-- Gambar / keadaan kosong -->
        <button
          v-if="slot.foto"
          @click="preview = slot.foto"
          class="relative aspect-video bg-black/40 overflow-hidden group"
        >
          <img
            :src="fullUrl(slot.foto)"
            :alt="`Foto ${slot.judul}`"
            class="w-full h-full object-contain"
          />
          <span
            class="absolute inset-0 bg-black/0 group-hover:bg-black/30 transition-colors flex items-center justify-center"
          >
            <span
              class="opacity-0 group-hover:opacity-100 text-[9px] font-black uppercase tracking-widest text-white transition-opacity"
            >
              Perbesar
            </span>
          </span>
        </button>
        <div
          v-else
          class="aspect-video flex flex-col items-center justify-center gap-2 text-(--text-muted)"
        >
          <ImageOff class="w-6 h-6 opacity-40" />
          <span class="text-[9px] font-bold uppercase tracking-widest opacity-60">
            Belum ada foto
          </span>
          <button v-if="slot.label === 'blue_box' && cadanganBiru"
            @click="preview = cadanganBiru"
            class="px-2 text-[9px] leading-snug text-center text-warning hover:underline">
            Kamera bawah air tidak memberi frame — ada foto permukaan sebagai
            cadangan. Ketuk untuk melihat.
          </button>
        </div>

        <!-- Geo-tag ringkas -->
        <div class="px-3 py-2 min-h-[34px] flex items-center gap-1.5">
          <template v-if="slot.foto && geoRingkas(slot.foto)">
            <MapPin class="w-3 h-3 text-(--text-muted) shrink-0" />
            <span class="text-[9px] font-mono text-(--text-secondary) truncate">
              {{ geoRingkas(slot.foto) }}
            </span>
          </template>
          <span v-else-if="slot.foto" class="text-[9px] font-mono text-(--text-muted)">
            Tanpa metadata geo-tag
          </span>
        </div>
      </div>
    </div>

    <!-- Foto di luar slot penilaian — hasil TAKE_IMAGE -->
    <div v-if="lainnya.length" class="px-3 pb-3">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-[9px] font-black uppercase tracking-widest text-(--text-secondary)">
          Foto lain
        </span>
        <span class="text-[9px] text-(--text-muted)">di luar slot penilaian</span>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-3 gap-2">
        <div v-for="c in lainnya" :key="c.filename"
          class="rounded-lg border border-(--border-subtle) bg-(--bg-secondary) overflow-hidden flex flex-col">
          <button @click="preview = c" class="relative aspect-video bg-black/40 overflow-hidden group">
            <img :src="fullUrl(c)" :alt="c.label" class="w-full h-full object-contain" />
            <!-- Lencana kamera: satu-satunya cara operator tahu foto ini benar
                 diambil kamera bawah air, atau diam-diam jatuh ke permukaan. -->
            <span v-if="kameraFoto(c)"
              class="absolute top-1 left-1 text-[8px] font-black px-1.5 py-0.5 rounded"
              :class="kameraFoto(c).startsWith('bawah air')
                ? 'bg-sky-500/80 text-white' : 'bg-black/70 text-white/80'">
              {{ kameraFoto(c).startsWith('bawah air') ? 'BAWAH AIR' : 'PERMUKAAN' }}
            </span>
          </button>
          <div class="px-2 py-1.5 flex flex-col gap-0.5">
            <span class="text-[9px] font-bold text-(--text-primary) truncate">{{ c.label || '—' }}</span>
            <span v-if="geoRingkas(c)" class="text-[8px] font-mono text-(--text-secondary) truncate">
              {{ geoRingkas(c) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="errorMsg" class="px-3 pb-3 text-[10px] font-bold text-danger">
      {{ errorMsg }}
    </div>

    <!-- Preview besar -->
    <Teleport to="body">
      <div
        v-if="preview"
        @click="tutupPreview"
        class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-6"
      >
        <div class="max-w-5xl w-full max-h-full flex flex-col gap-3" @click.stop>
          <img
            :src="fullUrl(preview)"
            :alt="preview.filename"
            class="w-full max-h-[80vh] object-contain rounded-xl"
          />
          <div class="flex items-center justify-between gap-4">
            <span class="text-[10px] font-mono text-white/70 truncate">
              {{ preview.filename }}
            </span>
            <div class="flex items-center gap-3 shrink-0">
              <a
                :href="fullUrl(preview)"
                :download="preview.filename"
                class="text-[10px] font-black uppercase tracking-widest text-primary hover:brightness-125"
              >
                Unduh
              </a>
              <button
                @click="tutupPreview"
                class="text-[10px] font-black uppercase tracking-widest text-white/70 hover:text-white"
              >
                Tutup
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
