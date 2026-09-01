<script setup>
/**
 * Pemilih sumber kendali manual: Mini PC (di kapal) vs Remote RC fisik.
 *
 * Dipakai untuk menjemput kapal saat misi gagal — tanpa perlu berenang. Saat
 * dipindah ke remote, Mini PC menghentikan SELURUH perintah geraknya (termasuk
 * netral yang dikirim tiap frame saat idle) lalu melepaskan RC override, sehingga
 * stik remote benar-benar memegang kemudi.
 *
 * Status yang ditampilkan SELALU berasal dari laporan kapal (telemetri /
 * MANUAL_SOURCE ACK), bukan dari tombol mana yang terakhir ditekan — supaya panel
 * ini tidak pernah menampilkan serah-terima yang sebenarnya tidak terjadi. Karena
 * itu ada indikator "menunggu kapal": tanpa itu, klik yang belum dijawab kapal
 * terlihat persis seperti tombol rusak.
 */
import { computed, ref, watch, onUnmounted } from 'vue';
import { Cpu, Radio, Loader2 } from 'lucide-vue-next';
import { useWebsocketStore } from '@/stores/websocketStore';
import { useVesselStore } from '@/stores/vesselStore';

const ws = useWebsocketStore();
const vessel = useVesselStore();

const isConnected = computed(() => ws.status === 'CONNECTED');
const isRemote = computed(() => vessel.manualSource === 'remote');

// Saat switch fisik di remote yang menentukan sumber kendali, POSISI SWITCH SELALU
// MENANG — menekan tombol di bawah akan dikembalikan kapal dalam sepersekian detik.
// Tanpa penjelasan ini tombolnya terlihat rusak, dan operator akan menekannya
// berulang-ulang di saat yang justru genting.
const byRcSwitch = computed(() => vessel.rcSourceSwitch === true);

// Perintah terkirim tapi kapal belum menjawab.
const pending = ref(null);      // 'minipc' | 'remote' | null
const timedOut = ref(false);
let pendingTimer = null;

function clearPending() {
  pending.value = null;
  if (pendingTimer) clearTimeout(pendingTimer);
  pendingTimer = null;
}

function startPending(target) {
  pending.value = target;
  timedOut.value = false;
  if (pendingTimer) clearTimeout(pendingTimer);
  // Kapal membalas ACK dalam hitungan milidetik kalau memang mendengarkan.
  // Kalau 5 detik tidak ada jawaban, kemungkinan besar Mini PC menjalankan versi
  // kode yang belum mengenal perintah ini — beri tahu, jangan diam saja.
  pendingTimer = setTimeout(() => {
    if (pending.value) {
      timedOut.value = true;
      pending.value = null;
    }
  }, 5000);
}

watch(() => vessel.manualSource, () => {
  clearPending();
  timedOut.value = false;
});

onUnmounted(clearPending);

// Menyerahkan ke remote SENGAJA tanpa dialog konfirmasi: ini arah darurat (kapal
// ngaco, harus segera diambil alih) dan dialog cuma menambah jeda. Arah sebaliknya
// yang dikonfirmasi — itu yang menyalakan kembali kendali otomatis.
function handoverToRemote() {
  if (!isConnected.value || isRemote.value) return;
  startPending('remote');
  ws.setManualSource('remote');
}

function takeBackToMinipc() {
  if (!isConnected.value || !isRemote.value) return;
  const ok = window.confirm(
    'Kembalikan kemudi ke MINI PC?\n\n' +
    'Remote RC fisik tidak lagi memegang kendali setelah ini. ' +
    'Pastikan kapal sudah aman dan operator remote sudah tahu.'
  );
  if (!ok) return;
  startPending('minipc');
  ws.setManualSource('minipc');
}
</script>

<template>
  <div class="glass-card p-4 space-y-3 border-t-4"
    :class="isRemote ? 'border-t-warning' : 'border-t-primary'">

    <div class="flex items-center justify-between">
      <span class="text-xs font-bold uppercase tracking-widest text-(--text-primary) flex items-center gap-1.5">
        <Radio class="w-4 h-4" :class="isRemote ? 'text-warning' : 'text-primary'" />
        Sumber Kendali
      </span>
      <span class="text-[9px] px-2 py-0.5 rounded font-bold"
        :class="isRemote ? 'bg-warning/10 text-warning' : 'bg-success/10 text-success'">
        {{ isRemote ? 'REMOTE RC' : 'MINI PC' }}
      </span>
    </div>

    <div v-if="byRcSwitch"
      class="flex items-start gap-2 p-2.5 rounded-lg bg-info/10 border border-info/30">
      <Radio class="w-3.5 h-3.5 text-info shrink-0 mt-0.5" />
      <span class="text-[10px] leading-relaxed text-(--text-secondary)">
        Dikendalikan <b class="text-info">switch di remote</b><template v-if="vessel.rcSourceChannel">
        (ch{{ vessel.rcSourceChannel }})</template>. Posisi switch selalu menang —
        tombol di bawah hanya penunjuk keadaan, dan akan dikembalikan kapal kalau ditekan.
      </span>
    </div>

    <div class="space-y-2">
      <button type="button" @click="takeBackToMinipc" :disabled="!isConnected" :class="[
        'w-full flex items-start gap-2.5 p-3 rounded-lg border text-left transition-colors',
        !isConnected ? 'opacity-50 cursor-not-allowed' : '',
        !isRemote
          ? 'bg-success/10 border-success/40 text-success'
          : 'bg-(--bg-secondary) border-(--border-subtle) text-(--text-secondary) hover:border-(--border-primary)'
      ]">
        <Loader2 v-if="pending === 'minipc'" class="w-4 h-4 mt-0.5 shrink-0 animate-spin" />
        <Cpu v-else class="w-4 h-4 mt-0.5 shrink-0" />
        <span>
          <span class="block text-sm font-bold">Mini PC (di kapal)</span>
          <span class="block text-[11px] opacity-80 mt-0.5">
            Misi otomatis &amp; joystick base station aktif.
          </span>
        </span>
      </button>

      <button type="button" @click="handoverToRemote" :disabled="!isConnected" :class="[
        'w-full flex items-start gap-2.5 p-3 rounded-lg border text-left transition-colors',
        !isConnected ? 'opacity-50 cursor-not-allowed' : '',
        isRemote
          ? 'bg-warning/10 border-warning/40 text-warning'
          : 'bg-(--bg-secondary) border-(--border-subtle) text-(--text-secondary) hover:border-(--border-primary)'
      ]">
        <Loader2 v-if="pending === 'remote'" class="w-4 h-4 mt-0.5 shrink-0 animate-spin" />
        <Radio v-else class="w-4 h-4 mt-0.5 shrink-0" />
        <span>
          <span class="block text-sm font-bold">Remote RC fisik</span>
          <span class="block text-[11px] opacity-80 mt-0.5">
            Untuk menjemput kapal. Misi di-abort, mode dipaksa MANUAL.
          </span>
        </span>
      </button>
    </div>

    <p v-if="!isConnected" class="text-[11px] text-(--text-secondary)">
      Base station belum terhubung — tombol nonaktif.
    </p>
    <p v-else-if="pending" class="text-[11px] text-(--text-secondary)">
      Menunggu konfirmasi dari kapal…
    </p>
    <p v-else-if="timedOut" class="text-[11px] text-warning">
      Kapal tidak menjawab. Pastikan Mini PC sudah menjalankan versi terbaru
      (<code>git pull</code> lalu restart <code>main.py</code>).
    </p>
    <p v-else class="text-[11px] text-(--text-secondary)">
      Kalau Mini PC mati, Pixhawk mengembalikan kemudi ke remote setelah ±3 detik.
    </p>
  </div>
</template>
