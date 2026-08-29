<script setup>
import Sidebar from "./Sidebar.vue";
import Topbar from "./Topbar.vue";
</script>

<template>
  <div class="flex h-screen w-full bg-background text-slate-200 overflow-hidden">
    <!-- Sidebar -->
    <Sidebar />

    <!-- Main Content Area -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Topbar -->
      <Topbar />

      <!-- View Container -->
      <main class="flex-1 overflow-hidden relative">
        <slot />
      </main>
      
      <!-- System Notification Bar (Optional) -->
      <div class="h-8 bg-slate-900 border-t border-slate-800 hidden sm:flex items-center px-6 justify-between text-[10px] uppercase tracking-widest font-bold text-slate-500">
        <div class="flex gap-4">
          <span>CPU: 12%</span>
          <span>MEM: 240MB</span>
          <span>DISK: 82%</span>
        </div>
        <div class="flex gap-4">
          <span>LATENCY: 42ms</span>
          <span>FPS: 60</span>
        </div>
      </div>
    </div>
  </div>
</template>
