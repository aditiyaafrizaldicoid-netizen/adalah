import { createRouter, createWebHistory } from "vue-router";
import Dashboard from "../views/Dashboard.vue";

const routes = [
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
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

export default router;
