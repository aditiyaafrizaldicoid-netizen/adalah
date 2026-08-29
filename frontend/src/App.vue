<script setup>
import { computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import MainLayout from "./layout/MainLayout.vue";
import { useWebsocketStore } from "./stores/websocketStore";

const wsStore = useWebsocketStore();
const route = useRoute();

// Route publik (login) tampil penuh layar, tanpa sidebar dan topbar.
const layout = computed(() => (route.meta.public ? "div" : MainLayout));

onMounted(() => {
  wsStore.connect();
});
</script>

<template>
  <component :is="layout">
    <router-view v-slot="{ Component }">
      <transition
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="transform opacity-0 translate-y-4"
        enter-to-class="transform opacity-100 translate-y-0"
        leave-active-class="transition duration-100 ease-in"
        leave-from-class="transform opacity-100 translate-y-0"
        leave-to-class="transform opacity-0 translate-y-4"
        mode="out-in"
      >
        <component :is="Component" />
      </transition>
    </router-view>
  </component>
</template>

<style>
/* Reset default transition behavior if needed */
</style>
