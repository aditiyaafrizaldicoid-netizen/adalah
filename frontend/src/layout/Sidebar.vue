<script setup>
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useRouter, useRoute } from "vue-router";
import {
  LayoutDashboard,
  Activity,
  Map as MapIcon,
  Flag,
  Settings2,
  Trophy,
  Stethoscope,
  Database,
  Gamepad2,
  ChevronLeft,
  ChevronRight,
} from "lucide-vue-next";
import { useThemeStore } from '@/stores/themeStore';
import { useUiStore } from '@/stores/uiStore';

const router = useRouter();
const route = useRoute();
const themeStore = useThemeStore();
const ui = useUiStore();
const isCollapsed = ref(false);

// Di layar sempit sidebar berubah jadi DRAWER yang menutupi konten, bukan kolom
// tetap: dengan lebar 256px ia memakan lebih dari separuh layar ponsel.
const DESKTOP_QUERY = '(min-width: 1024px)';   // = breakpoint `lg` Tailwind
const isDesktop = ref(typeof window !== 'undefined'
  ? window.matchMedia(DESKTOP_QUERY).matches : true);

let mq = null;
const onBreakpointChange = (e) => {
  isDesktop.value = e.matches;
  // Kembali ke layar lebar: pastikan drawer tidak tertinggal "terbuka", karena di
  // sana sidebar memang selalu tampil dan backdrop-nya akan menghalangi konten.
  if (e.matches) ui.closeSidebar();
};

onMounted(() => {
  mq = window.matchMedia(DESKTOP_QUERY);
  mq.addEventListener('change', onBreakpointChange);
});
onUnmounted(() => {
  if (mq) mq.removeEventListener('change', onBreakpointChange);
});

// Mode ringkas (ikon saja) HANYA berlaku di layar lebar. Sebagai drawer, sidebar
// selalu tampil penuh dengan label — di ponsel tidak ada hover untuk memunculkan
// tooltip nama menu, jadi ikon tanpa label akan menjadi tebak-tebakan.
const collapsed = computed(() => isCollapsed.value && isDesktop.value);

/**
 * Posisi drawer, diturunkan langsung dari state sebagai style.
 *
 * Sebelumnya disusun dari TIGA utility yang menulis properti yang sama:
 * `lg:translate-x-0`, `translate-x-0`, dan `-translate-x-full`. Di Tailwind v4
 * ketiganya menulis `translate` lewat variabel `--tw-translate-x`, sehingga siapa
 * yang menang ditentukan urutan di CSS hasil build — bukan urutan di atribut
 * class, dan bukan sesuatu yang terbaca dari berkas ini.
 *
 * CATATAN JUJUR: versi lama itu diuji dan ternyata BEKERJA. Ini penyederhanaan
 * supaya perilakunya bisa dibaca langsung dari satu ekspresi, bukan perbaikan bug.
 * Bug yang sebenarnya membuat menu tidak bisa dibuka di ponsel ada di Topbar —
 * lihat catatan di layout/Topbar.vue.
 */
const gayaGeser = computed(() => ({
  transform: (isDesktop.value || ui.sidebarOpen) ? 'translateX(0)' : 'translateX(-100%)',
}));

const isDark = computed(() => themeStore.theme === 'dark');

const menuItems = [
  { name: "Dashboard", path: "/", icon: LayoutDashboard },
  { name: "Manual Control", path: "/manual", icon: Gamepad2 },
  { name: "Monitoring", path: "/monitoring", icon: Activity },
  { name: "Mapping", path: "/mapping", icon: MapIcon },
  { name: "Mission Control", path: "/mission", icon: Flag },
  { name: "Calibration", path: "/calibration", icon: Settings2 },
  { name: "Scoring", path: "/scoring", icon: Trophy },
  { name: "Diagnostics", path: "/diagnostics", icon: Stethoscope },
  { name: "Data Manager", path: "/data", icon: Database },
];

const navigate = (path) => {
  router.push(path);
  ui.closeSidebar();   // di ponsel drawer harus menutup setelah memilih menu
};
</script>

<template>
  <!-- Backdrop drawer (hanya layar sempit) -->
  <div
    v-if="ui.sidebarOpen"
    @click="ui.closeSidebar()"
    class="fixed inset-0 bg-black/50 z-40 lg:hidden"
    aria-hidden="true"
  ></div>

  <aside
    :class="[
      'bg-(--bg-sidebar) border-r border-(--border-primary) transition-all duration-300 flex flex-col',
      // Layar sempit: drawer melayang di atas konten, digeser keluar layar saat tutup.
      // Layar lebar (lg+): kembali jadi kolom biasa dalam alur flex MainLayout.
      'fixed inset-y-0 left-0 z-50 w-64 lg:static lg:z-auto',
      collapsed ? 'lg:w-20' : 'lg:w-64',
    ]"
    :style="gayaGeser"
  >
    <!-- Logo Section -->
    <div class="p-6 flex items-center justify-between border-b border-(--border-primary)">
      <div v-if="!collapsed" class="flex items-center gap-3">
        <div class="w-8 h-8 bg-(--accent-primary) rounded-lg flex items-center justify-center">
          <Activity class="text-white w-5 h-5" />
        </div>
        <span class="font-bold text-xl tracking-tight text-(--text-primary)">UMM<span class="text-(--accent-primary)"> STATION</span></span>
      </div>
      <div v-else class="w-full flex justify-center">
        <div class="w-10 h-10 bg-(--accent-primary) rounded-lg flex items-center justify-center">
          <Activity class="text-white w-6 h-6" />
        </div>
      </div>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 p-4 space-y-2 overflow-y-auto">
      <button
        v-for="item in menuItems"
        :key="item.path"
        @click="navigate(item.path)"
        :class="[
          'w-full flex items-center gap-4 px-4 py-3 rounded-xl transition-all group relative font-semibold',
          route.path === item.path
            ? 'bg-(--accent-primary) text-white shadow-lg shadow-red-900/20'
            : 'text-(--text-secondary) hover:bg-(--bg-hover) hover:text-(--text-primary)',
        ]"
      >
        <component :is="item.icon" :size="20" :stroke-width="2.5" />
        <span v-if="!collapsed">{{ item.name }}</span>
        
        <!-- Tooltip for collapsed mode -->
        <div
          v-if="collapsed"
          class="absolute left-full ml-4 px-3 py-1 bg-(--bg-card) text-(--text-primary) text-sm rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-50 border border-(--border-primary) shadow-xl"
        >
          {{ item.name }}
        </div>
      </button>
    </nav>

    <!-- Collapse Toggle -->
    <div class="p-4 border-t border-(--border-primary) hidden lg:block">
      <button
        @click="isCollapsed = !isCollapsed"
        class="w-full flex items-center justify-center p-2 rounded-lg bg-(--bg-secondary) text-(--text-secondary) hover:text-(--text-primary) transition-colors border border-(--border-subtle)"
      >
        <ChevronLeft v-if="!collapsed" />
        <ChevronRight v-else />
      </button>
    </div>
  </aside>
</template>
