import { createRouter, createWebHistory } from "vue-router";
import Dashboard from "../views/Dashboard.vue";

const routes = [
  {
    path: "/login",
    name: "Login",
    component: () => import("../views/Login.vue"),
    meta: { public: true },
  },
  {
    path: "/",
    name: "Dashboard",
    component: Dashboard,
  },
  {
    path: "/monitoring",
    name: "Monitoring",
    component: () => import("../views/Monitoring.vue"),
  },
  {
    path: "/mapping",
    name: "Mapping",
    component: () => import("../views/Mapping.vue"),
  },
  {
    path: "/mission",
    name: "MissionControl",
    component: () => import("../views/MissionControl.vue"),
  },
  {
    path: "/calibration",
    name: "Calibration",
    component: () => import("../views/Calibration.vue"),
  },
  {
    path: "/scoring",
    name: "Scoring",
    component: () => import("../views/Scoring.vue"),
  },
  {
    path: "/diagnostics",
    name: "Diagnostics",
    component: () => import("../views/Diagnostics.vue"),
  },
  {
    path: "/data",
    name: "DataManager",
    component: () => import("../views/DataManager.vue"),
  },
  {
    path: "/manual",
    name: "ManualControl",
    component: () => import("../views/ManualControl.vue"),
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

// Proteksi route masih dimatikan supaya halaman lama tetap bisa diakses seperti
// sekarang. Ubah ke true kalau login sudah mau diwajibkan.
const ENFORCE_AUTH = false;

router.beforeEach((to) => {
  if (!ENFORCE_AUTH) return true;

  const isAuthenticated = !!localStorage.getItem("asv_access_token");

  if (!to.meta.public && !isAuthenticated) {
    return { name: "Login", query: { redirect: to.fullPath } };
  }
  if (to.meta.public && isAuthenticated) {
    return { path: "/" };
  }
  return true;
});

export default router;
