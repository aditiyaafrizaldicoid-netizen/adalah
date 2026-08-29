<script setup>
import { ref, onMounted, onUnmounted, computed } from "vue";
import {
  Battery,
  Clock,
  Zap,
  Radio,
  Sun,
  Moon,
  ShieldOff,
  LogOut,
  LogIn,
  User,
  Menu
} from "lucide-vue-next";
import { useRouter } from 'vue-router';
import { useVesselStore } from '@/stores/vesselStore';
import { useThemeStore } from '@/stores/themeStore';
import { useWebsocketStore } from '@/stores/websocketStore';
import { useMissionStore } from '@/stores/missionStore';
import { useAuthStore } from '@/stores/authStore';
import { useUiStore } from '@/stores/uiStore';
import { formatTime } from '@/utils/geotag';

const vessel = useVesselStore();
const ui = useUiStore();
const themeStore = useThemeStore();
const wsStore = useWebsocketStore();
const mission = useMissionStore();
const auth = useAuthStore();
const router = useRouter();

const isKillActive = ref(false);

function handleKillSwitch() {
  isKillActive.value = true;
  // 1. Abort mission (sends abort_mission command via WebSocket)
  mission.abortMission();
  // 2. Disarm vehicle
  wsStore.sendCommand({ action: 'disarm' });
  // Reset visual feedback after 2s
  setTimeout(() => { isKillActive.value = false; }, 2000);
}

const killLabel = computed(() => {
  if (isKillActive.value) return 'STOPPING...';
  if (mission.missionStatus === 'RUNNING') return 'KILL MISSION';
  return 'KILL SWITCH';
});

// 24 jam hh:mm:ss, bukan toLocaleTimeString() yang menghasilkan "10:45:49 PM" —
// lembar ketentuan meminta format hh:mm:ss, dan jam 12-jam di sebelah panel geo-tag
// yang 24-jam hanya membingungkan saat dinilai.
const currentTime = ref(formatTime(new Date()));
const isDark = computed(() => themeStore.theme === 'dark');

let timer;
onMounted(() => {
  timer = setInterval(() => {
    currentTime.value = formatTime(new Date());
  }, 1000);
});

onUnmounted(() => {
  clearInterval(timer);
});

// Nama panggilan saja — Topbar sudah padat, nama lengkap bikin baris ini melar.
const userLabel = computed(() => auth.user?.name?.split(' ')[0] || 'Operator');

async function handleLogout() {
  await auth.logout();
  router.push({ name: 'Login' });
}
</script>

<template>
  <header class="h-16 bg-(--bg-topbar) border-b border-(--border-primary) flex items-center justify-between px-3 sm:px-8 z-40 transition-colors duration-300">
    <div class="flex items-center gap-3 sm:gap-6 min-w-0">
      <!-- Pembuka drawer sidebar — hanya muncul saat sidebar tidak tampil sendiri -->
      <button
        @click="ui.toggleSidebar()"
        class="lg:hidden p-2 -ml-1 rounded-lg text-(--text-secondary) hover:text-(--text-primary) hover:bg-(--bg-hover) transition-colors shrink-0"
        aria-label="Buka menu"
      >
        <Menu class="w-5 h-5" />
      </button>

      <div class="flex items-center gap-2 min-w-0">
        <div 
          :class="[
            'w-2 h-2 rounded-full animate-pulse',
            wsStore.status === 'CONNECTED' ? 'bg-success' : (wsStore.status === 'CONNECTING' ? 'bg-warning' : 'bg-danger')
          ]"
        ></div>
        <span class="text-[10px] sm:text-xs font-bold uppercase tracking-widest text-(--text-secondary) truncate">
          <span class="hidden sm:inline">Vessel Status:&nbsp;</span>
          <span :class="wsStore.status === 'CONNECTED' ? 'text-success' : (wsStore.status === 'CONNECTING' ? 'text-warning' : 'text-danger')">
            {{ wsStore.status }}
          </span>
        </span>
      </div>
      
      <div class="h-4 w-px bg-(--border-primary) hidden md:block"></div>

      <div class="hidden md:flex items-center gap-3 bg-(--bg-secondary) px-3 py-1.5 rounded-full border border-(--border-subtle)">
        <Radio class="w-4 h-4 text-primary" />
        <span class="text-xs font-mono text-(--text-primary)">ASV Backend WS</span>
      </div>
    </div>

    <div class="flex items-center gap-2 sm:gap-6 shrink-0">
      <!-- Theme Toggle -->
      <button @click="themeStore.toggleTheme()"
        class="p-2 rounded-lg transition-all duration-300 border border-(--border-primary)"
        :class="isDark
          ? 'bg-(--bg-card) text-(--accent-secondary)'
          : 'bg-(--bg-card) text-(--accent-primary)'">
        <Moon v-if="isDark" class="w-5 h-5" />
        <Sun v-else class="w-5 h-5" />
      </button>



      <div class="flex items-center gap-2 sm:gap-4 text-(--text-secondary)">
        <div class="hidden sm:flex items-center gap-2">
          <Battery class="w-5 h-5 text-success" />
          <span class="text-sm font-mono font-bold text-(--text-primary)">{{ vessel.batteryPct.toFixed(2) }}%</span>
        </div>
        <div class="flex items-center gap-2">
          <Clock class="w-5 h-5 text-primary" />
          <span class="text-sm font-mono font-bold text-(--text-primary)">{{ currentTime }}</span>
        </div>
      </div>
      
      <div class="h-4 w-px bg-(--border-primary) hidden sm:block"></div>

      <!-- Sesi operator. Fallback "Masuk" tetap perlu: token bisa kedaluwarsa atau
           dibersihkan saat aplikasi terbuka, tanpa navigasi baru yang memicu guard. -->
      <div v-if="auth.isAuthenticated" class="flex items-center gap-2">
        <div class="flex items-center gap-2 bg-(--bg-secondary) px-3 py-1.5 rounded-full border border-(--border-subtle)">
          <User class="w-4 h-4 text-primary" />
          <span class="text-xs font-bold text-(--text-primary)">{{ userLabel }}</span>
          <span class="text-[10px] font-bold uppercase tracking-widest text-(--text-muted)">
            {{ auth.user?.role }}
          </span>
        </div>
        <button
          @click="handleLogout"
          title="Keluar"
          class="p-2 rounded-lg border border-(--border-primary) bg-(--bg-card) text-(--text-secondary) hover:text-danger hover:border-danger transition-all active:scale-95">
          <LogOut class="w-5 h-5" />
        </button>
      </div>

      <router-link
        v-else
        :to="{ name: 'Login' }"
        class="flex items-center gap-2 px-4 py-2 rounded-lg border border-(--border-primary) bg-(--bg-card) text-xs font-bold uppercase tracking-wider text-(--text-secondary) hover:text-(--accent-primary) hover:border-(--border-accent) transition-all active:scale-95">
        <LogIn class="w-4 h-4" />
        Masuk
      </router-link>

      <button
        @click="handleKillSwitch"
        :disabled="isKillActive"
        :class="[
          'px-5 py-2 rounded-lg font-black text-xs flex items-center gap-2 transition-all active:scale-95 uppercase tracking-wider shadow-lg',
          isKillActive
            ? 'bg-orange-600 text-white cursor-not-allowed shadow-orange-600/30 animate-pulse'
            : (mission.missionStatus === 'RUNNING' || vessel.isArmed) ? 'bg-danger hover:bg-red-600 text-white shadow-danger/30 animate-pulse'
              : 'bg-danger/80 hover:bg-danger text-white shadow-danger/20'
        ]">
        <ShieldOff class="w-4 h-4" />
        {{ killLabel }}
      </button>
    </div>
  </header>
</template>
