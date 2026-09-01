import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/authStore";
import Dashboard from "../views/Dashboard.vue";

const routes = [
  {
    path: "/login",
    name: "Login",
    component: () => import("../views/Login.vue"),
    // guestOnly: sudah login berarti tidak perlu form login lagi.
    meta: { public: true, guestOnly: true },
  },
  {
    path: "/juri",
    name: "Juri",
    component: () => import("../views/Juri.vue"),
    // Publik tanpa guestOnly: panel baca-saja ini harus bisa dibuka juri tanpa
    // login, dan tetap bisa dibuka operator yang sedang login.
    meta: { public: true },
  },
  {
    path: "/",
    name: "Dashboard",
    component: Dashboard,
    meta: { requiresAuth: true },
  },
  {
    path: "/monitoring",
    name: "Monitoring",
    component: () => import("../views/Monitoring.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/mapping",
    name: "Mapping",
    component: () => import("../views/Mapping.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/mission",
    name: "MissionControl",
    component: () => import("../views/MissionControl.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/calibration",
    name: "Calibration",
    component: () => import("../views/Calibration.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/scoring",
    name: "Scoring",
    component: () => import("../views/Scoring.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/diagnostics",
    name: "Diagnostics",
    component: () => import("../views/Diagnostics.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/data",
    name: "DataManager",
    component: () => import("../views/DataManager.vue"),
    meta: { requiresAuth: true },
  },
  {
    path: "/manual",
    name: "ManualControl",
    component: () => import("../views/ManualControl.vue"),
    meta: { requiresAuth: true },
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to) => {
  // Sesi disimpan di sessionStorage, jadi menutup browser sudah membuang tokennya
  // (lihat utils/session.js). Yang diperiksa di sini adalah dua hal yang dulu tidak
  // diperiksa sama sekali: apakah tokennya masih BERLAKU, dan kalau sudah habis
  // apakah masih bisa ditukar dengan yang baru. Sebelumnya guard ini hanya melihat
  // APAKAH ADA token, sehingga token yang sudah lewat 1 jam tetap meloloskan
  // operator ke seluruh aplikasi — dan kegagalannya baru terasa saat perintah ke
  // kapal mulai ditolak.
  const auth = useAuthStore();
  const isAuthenticated = await auth.ensureFreshSession();

  if (!to.meta.public && !isAuthenticated) {
    return { name: "Login", query: { redirect: to.fullPath } };
  }
  if (to.meta.guestOnly && isAuthenticated) {
    return { path: "/" };
  }
  return true;
});

export default router;
