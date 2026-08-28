<script setup>
defineProps({
  label: String,
  value: [String, Number],
  unit: String,
  icon: [Object, Function],
  color: {
    type: String,
    default: 'primary'
  },
  trend: String,
  // Catatan kaki opsional, mis. alasan sebuah nilai sedang tidak tersedia.
  // Dipakai COG saat kapal terlalu pelan untuk punya arah gerak yang berarti.
  note: String
});
</script>

<template>
  <div class="glass-card p-4 relative overflow-hidden group hover:border-primary/50 transition-all duration-300">
    <div class="flex justify-between items-start relative z-10">
      <div>
        <span class="text-[10px] font-bold text-(--text-secondary) uppercase tracking-widest block mb-1">{{ label }}</span>
        <div class="flex items-baseline gap-1">
          <span class="text-2xl font-black text-(--text-primary) font-mono">{{ value }}</span>
          <span class="text-[10px] font-bold text-(--text-secondary) uppercase">{{ unit }}</span>
        </div>
      </div>
      <div :class="[
        'w-10 h-10 rounded-lg flex items-center justify-center transition-transform group-hover:scale-110',
        color === 'primary' ? 'bg-primary/20 text-primary' :
        color === 'success' ? 'bg-success/20 text-success' :
        color === 'warning' ? 'bg-warning/20 text-warning' :
        color === 'danger' ? 'bg-danger/20 text-danger' : 'bg-(--bg-secondary)/50 text-(--text-secondary)'
      ]">
        <component :is="icon" class="w-5 h-5" />
      </div>
    </div>
    
    <div v-if="trend" class="mt-3 flex items-center gap-1">
      <span class="text-[10px] font-bold text-success">{{ trend }} ↑</span>
      <span class="text-[10px] text-(--text-muted) font-bold uppercase">vs last session</span>
    </div>
    <div v-else-if="note" class="mt-3">
      <span class="text-[10px] text-(--text-muted) font-bold uppercase">{{ note }}</span>
    </div>

    <!-- Decorative element -->
    <div :class="[
      'absolute -right-4 -bottom-4 w-16 h-16 blur-2xl opacity-10 transition-opacity group-hover:opacity-20',
      color === 'primary' ? 'bg-primary' :
      color === 'success' ? 'bg-success' :
      color === 'warning' ? 'bg-warning' :
      color === 'danger' ? 'bg-danger' : 'bg-(--bg-secondary)'
    ]"></div>
  </div>
</template>
