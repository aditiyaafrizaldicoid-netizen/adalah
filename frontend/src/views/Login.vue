<script setup>
import { ref, computed, onMounted } from "vue";
import { useRouter, useRoute } from "vue-router";
import {
  Activity,
  Mail,
  Lock,
  Eye,
  EyeOff,
  LogIn,
  AlertTriangle,
  Sun,
  Moon,
  ShieldCheck,
} from "lucide-vue-next";
import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";
import heroImage from "@/assets/hero.png";

const router = useRouter();
const route = useRoute();
const auth = useAuthStore();
const themeStore = useThemeStore();

const email = ref("");
const password = ref("");
const showPassword = ref(false);

const isDark = computed(() => themeStore.theme === "dark");
const canSubmit = computed(
  () => email.value.trim() !== "" && password.value !== "" && !auth.isLoading
);

onMounted(() => {
  // Sisa sesi lama dibuang supaya form selalu mulai bersih.
  auth.error = "";
});

async function handleSubmit() {
  if (!canSubmit.value) return;
  const ok = await auth.login(email.value.trim(), password.value);
  if (ok) {
    // redirect=... dipakai router guard saat proteksi route diaktifkan.
    router.replace(route.query.redirect || "/");
  } else {
    password.value = "";
  }
}
</script>

<template>
  <div class="h-screen w-screen flex bg-(--bg-primary) overflow-hidden">
    <!-- Panel Branding (kiri) -->
    <div class="hidden lg:flex flex-1 relative border-r border-(--border-primary)">
      <img
        :src="heroImage"
        alt=""
        class="absolute inset-0 w-full h-full object-cover"
        :class="isDark ? 'opacity-25' : 'opacity-20'"
      />
      <div
        class="absolute inset-0"
        :style="{
          background: isDark
            ? 'linear-gradient(135deg, rgba(21,5,5,0.96) 0%, rgba(200,16,46,0.28) 100%)'
            : 'linear-gradient(135deg, rgba(253,240,240,0.94) 0%, rgba(200,16,46,0.18) 100%)',
        }"
      ></div>

      <div class="relative z-10 flex flex-col justify-between p-12 w-full">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 bg-(--accent-primary) rounded-lg flex items-center justify-center">
            <Activity class="text-white w-6 h-6" />
          </div>
          <span class="font-bold text-2xl tracking-tight text-(--text-primary)">
            UMM<span class="text-(--accent-primary)"> STATION</span>
          </span>
        </div>

        <div>
          <p class="text-[10px] font-bold uppercase tracking-[0.3em] text-(--accent-secondary) mb-4">
            Autonomous Surface Vehicle
          </p>
          <h1 class="text-4xl xl:text-5xl font-bold text-(--text-primary) leading-tight mb-4">
            Ground Control<br />Base Station
          </h1>
          <p class="text-(--text-secondary) text-sm max-w-md leading-relaxed">
            Telemetri, misi, kalibrasi, dan penilaian dalam satu konsol. Masuk dengan
            akun operator untuk mulai mengendalikan armada.
          </p>
        </div>

        <div class="flex items-center gap-6 text-[10px] font-bold uppercase tracking-widest text-(--text-muted)">
          <span class="flex items-center gap-2">
            <ShieldCheck class="w-3.5 h-3.5 text-(--status-ok)" /> Secure Session
          </span>
          <span>v1.1</span>
        </div>
      </div>
    </div>

    <!-- Panel Form (kanan) -->
    <div class="flex-1 flex flex-col items-center justify-center px-6 py-10 relative overflow-y-auto">
      <!-- Toggle tema -->
      <button
        type="button"
        @click="themeStore.toggleTheme()"
        class="absolute top-6 right-6 p-2.5 rounded-xl border border-(--border-primary) bg-(--bg-secondary) text-(--text-secondary) hover:text-(--accent-primary) hover:border-(--border-accent) transition-all active:scale-95"
        :title="isDark ? 'Mode terang' : 'Mode gelap'"
      >
        <Sun v-if="isDark" class="w-4 h-4" />
        <Moon v-else class="w-4 h-4" />
      </button>

      <div class="w-full max-w-sm">
        <!-- Logo untuk layar kecil -->
        <div class="flex lg:hidden items-center gap-3 mb-10 justify-center">
          <div class="w-9 h-9 bg-(--accent-primary) rounded-lg flex items-center justify-center">
            <Activity class="text-white w-5 h-5" />
          </div>
          <span class="font-bold text-xl tracking-tight text-(--text-primary)">
            UMM<span class="text-(--accent-primary)"> STATION</span>
          </span>
        </div>

        <p class="text-[10px] font-bold uppercase tracking-[0.3em] text-(--accent-primary) mb-2">
          Operator Access
        </p>
        <h2 class="text-2xl font-bold text-(--text-primary) mb-1">Masuk ke Base Station</h2>
        <p class="text-sm text-(--text-secondary) mb-8">
          Gunakan kredensial yang terdaftar untuk melanjutkan.
        </p>

        <!-- Pesan error -->
        <div
          v-if="auth.error"
          class="flex items-start gap-3 mb-6 px-4 py-3 rounded-xl border border-(--status-error) bg-(--bg-hover)"
        >
          <AlertTriangle class="w-4 h-4 text-(--status-error) shrink-0 mt-0.5" />
          <p class="text-xs text-(--status-error) font-medium leading-relaxed">{{ auth.error }}</p>
        </div>

        <form class="space-y-5" @submit.prevent="handleSubmit">
          <!-- Email -->
          <div>
            <label
              for="login-email"
              class="block text-[10px] font-bold uppercase tracking-widest text-(--text-secondary) mb-2"
            >
              Email
            </label>
            <div class="relative">
              <Mail class="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-(--text-muted)" />
              <input
                id="login-email"
                v-model="email"
                type="email"
                autocomplete="username"
                placeholder="operator@mail.com"
                class="w-full pl-11 pr-4 py-3 rounded-xl bg-(--bg-secondary) border border-(--border-primary) text-sm text-(--text-primary) placeholder:text-(--text-muted) outline-none focus:border-(--border-accent) transition-colors"
              />
            </div>
          </div>

          <!-- Password -->
          <div>
            <label
              for="login-password"
              class="block text-[10px] font-bold uppercase tracking-widest text-(--text-secondary) mb-2"
            >
              Password
            </label>
            <div class="relative">
              <Lock class="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-(--text-muted)" />
              <input
                id="login-password"
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="current-password"
                placeholder="••••••••"
                class="w-full pl-11 pr-11 py-3 rounded-xl bg-(--bg-secondary) border border-(--border-primary) text-sm text-(--text-primary) placeholder:text-(--text-muted) outline-none focus:border-(--border-accent) transition-colors"
              />
              <button
                type="button"
                @click="showPassword = !showPassword"
                class="absolute right-3 top-1/2 -translate-y-1/2 p-1.5 rounded-lg text-(--text-muted) hover:text-(--text-primary) transition-colors"
                :title="showPassword ? 'Sembunyikan password' : 'Tampilkan password'"
              >
                <EyeOff v-if="showPassword" class="w-4 h-4" />
                <Eye v-else class="w-4 h-4" />
              </button>
            </div>
          </div>

          <!-- Tombol submit -->
          <button
            type="submit"
            :disabled="!canSubmit"
            class="w-full inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-xl bg-(--accent-primary) text-white text-xs font-bold uppercase tracking-widest hover:bg-(--accent-primary-hover) transition-all active:scale-95 disabled:opacity-50 disabled:active:scale-100 disabled:cursor-not-allowed"
          >
            <div
              v-if="auth.isLoading"
              class="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"
            ></div>
            <LogIn v-else class="w-4 h-4" />
            {{ auth.isLoading ? "Memverifikasi..." : "Masuk" }}
          </button>
        </form>

        <p class="mt-8 text-center text-[10px] uppercase tracking-widest text-(--text-muted)">
          Base Station ASV · Universitas Muhammadiyah Malang
        </p>
      </div>
    </div>
  </div>
</template>
