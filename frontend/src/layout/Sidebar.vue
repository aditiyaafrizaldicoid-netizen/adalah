<script setup>
import { ref, computed } from "vue";
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
  ChevronLeft,
  ChevronRight,
} from "lucide-vue-next";
import { useThemeStore } from '@/stores/themeStore';

const router = useRouter();
const route = useRoute();
const themeStore = useThemeStore();
const isCollapsed = ref(false);

const isDark = computed(() => themeStore.theme === 'dark');

const menuItems = [
  { name: "Dashboard", path: "/", icon: LayoutDashboard },
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
};
</script>

<template>
  <aside
    :class="[
      'bg-(--bg-sidebar) border-r border-(--border-primary) transition-all duration-300 flex flex-col',
      isCollapsed ? 'w-20' : 'w-64',
    ]"
  >
    <!-- Logo Section -->
    <div class="p-6 flex items-center justify-between border-b border-(--border-primary)">
      <div v-if="!isCollapsed" class="flex items-center gap-3">
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
        <span v-if="!isCollapsed">{{ item.name }}</span>
        
        <!-- Tooltip for collapsed mode -->
        <div
          v-if="isCollapsed"
          class="absolute left-full ml-4 px-3 py-1 bg-(--bg-card) text-(--text-primary) text-sm rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-50 border border-(--border-primary) shadow-xl"
        >
          {{ item.name }}
        </div>
      </button>
    </nav>

    <!-- Collapse Toggle -->
    <div class="p-4 border-t border-(--border-primary)">
      <button
        @click="isCollapsed = !isCollapsed"
        class="w-full flex items-center justify-center p-2 rounded-lg bg-(--bg-secondary) text-(--text-secondary) hover:text-(--text-primary) transition-colors border border-(--border-subtle)"
      >
        <ChevronLeft v-if="!isCollapsed" />
        <ChevronRight v-else />
      </button>
    </div>
  </aside>
</template>
