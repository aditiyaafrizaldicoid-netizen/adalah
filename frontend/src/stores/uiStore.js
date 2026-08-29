import { defineStore } from "pinia";
import { ref } from "vue";

/**
 * State tampilan yang dipakai bersama antar komponen layout.
 *
 * Sidebar dan Topbar bersaudara (dua-duanya anak MainLayout), jadi tombol hamburger
 * di Topbar tidak bisa langsung menyentuh state Sidebar lewat props. Store kecil ini
 * jembatannya — sengaja dipisah dari store domain (vessel/mission) karena isinya
 * murni urusan tampilan, bukan data kapal.
 */
export const useUiStore = defineStore("ui", () => {
  // Drawer sidebar di layar sempit. Di layar lebar sidebar selalu tampil dan nilai
  // ini tidak berpengaruh.
  const sidebarOpen = ref(false);

  const openSidebar = () => { sidebarOpen.value = true; };
  const closeSidebar = () => { sidebarOpen.value = false; };
  const toggleSidebar = () => { sidebarOpen.value = !sidebarOpen.value; };

  return { sidebarOpen, openSidebar, closeSidebar, toggleSidebar };
});
