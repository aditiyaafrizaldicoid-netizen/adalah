<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { useVesselStore } from '@/stores/vesselStore';

const props = defineProps({
  width: { type: Number, default: 800 },
  height: { type: Number, default: 600 },
  gridSize: { type: Number, default: 30 } // 30 meters
});

const vessel = useVesselStore();
const canvasRef = ref(null);
let ctx = null;
let animationId = null;

// Map state
const zoom = ref(20); // pixels per meter
const offsetX = ref(0);
const offsetY = ref(0);
const trail = ref([]); // Store position history [{x, y}]

// Watch vessel position and add to trail
watch(() => [vessel.lat, vessel.lng], ([lat, lng]) => {
  if (!vessel.isSimulating) return;
  
  // Convert GPS to mock local grid coordinates for trail
  const tx = (lng * 111111) / 100;
  const ty = -(lat * 111111) / 100;
  
  trail.value.push({ x: tx, y: ty });
  
  // Limit trail length to 200 points
  if (trail.value.length > 200) trail.value.shift();
}, { deep: true });

// Draw function
const draw = () => {
  if (!ctx) return;
  
  const style = getComputedStyle(document.documentElement);
  const bgColor = style.getPropertyValue('--bg-primary').trim();
  const gridColor = style.getPropertyValue('--border-primary').trim();
  const textColor = style.getPropertyValue('--text-muted').trim();

  const w = canvasRef.value.width;
  const h = canvasRef.value.height;
  
  // Clear
  ctx.fillStyle = bgColor || '#0f172a';
  ctx.fillRect(0, 0, w, h);
  
  // Center point
  const centerX = w / 2 + offsetX.value;
  const centerY = h / 2 + offsetY.value;
  
  // Draw Grid
  ctx.strokeStyle = gridColor || '#1e293b';
  ctx.lineWidth = 1;
  
  const step = zoom.value; // 1 meter in pixels
  
  // Vertical lines
  for (let x = centerX % step; x < w; x += step) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  
  // Horizontal lines
  for (let y = centerY % step; y < h; y += step) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  // Draw Origin Axis
  ctx.strokeStyle = textColor || '#334155';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(centerX, 0); ctx.lineTo(centerX, h);
  ctx.moveTo(0, centerY); ctx.lineTo(w, centerY);
  ctx.stroke();

  // Draw Trail
  if (trail.value.length > 1) {
    ctx.strokeStyle = 'rgba(200, 16, 46, 0.4)'; // Primary color with alpha
    ctx.lineWidth = 3;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    
    trail.value.forEach((p, index) => {
      const tx = centerX + p.x * zoom.value;
      const ty = centerY + p.y * zoom.value;
      if (index === 0) ctx.moveTo(tx, ty);
      else ctx.lineTo(tx, ty);
    });
    ctx.stroke();
  }

  // Draw Vessel (Simulated Local Position)
  // Mock conversion: 0.00001 degree ~ 1.11 meters
  const vesselX = centerX + (vessel.lng * 111111) * zoom.value / 100; 
  const vesselY = centerY - (vessel.lat * 111111) * zoom.value / 100; 
  
  ctx.save();
  ctx.translate(vesselX, vesselY);
  ctx.rotate((vessel.heading * Math.PI) / 180);
  
  // Vessel Shape
  ctx.fillStyle = '#38bdf8';
  ctx.beginPath();
  ctx.moveTo(0, -15);
  ctx.lineTo(10, 15);
  ctx.lineTo(0, 10);
  ctx.lineTo(-10, 15);
  ctx.closePath();
  ctx.fill();
  
  // Heading line
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 2;
  ctx.setLineDash([5, 5]);
  ctx.beginPath();
  ctx.moveTo(0, -15);
  ctx.lineTo(0, -50);
  ctx.stroke();
  
  ctx.restore();

  animationId = requestAnimationFrame(draw);
};

onMounted(() => {
  ctx = canvasRef.value.getContext('2d');
  draw();
});

onUnmounted(() => {
  cancelAnimationFrame(animationId);
});
</script>

<template>
  <div class="relative w-full h-full bg-background rounded-xl overflow-hidden cursor-crosshair">
    <canvas 
      ref="canvasRef" 
      :width="width" 
      :height="height"
      class="w-full h-full"
    ></canvas>
    
    <!-- Map Controls Overlay -->
    <div class="absolute bottom-4 right-4 flex flex-col gap-2">
      <button @click="zoom += 5" class="w-10 h-10 bg-card/80 text-(--text-primary) rounded-lg border border-(--border-subtle) hover:bg-primary transition-all">+</button>
      <button @click="zoom = Math.max(5, zoom - 5)" class="w-10 h-10 bg-card/80 text-(--text-primary) rounded-lg border border-(--border-subtle) hover:bg-primary transition-all">-</button>
    </div>

    <!-- Map Info Overlay -->
    <div class="absolute top-4 left-4 pointer-events-none">
      <div class="bg-(--bg-secondary)/90 border border-(--border-subtle) p-3 rounded-lg">
        <div class="flex items-center gap-2 mb-2">
          <div class="w-2 h-2 rounded-full bg-primary animate-pulse"></div>
          <span class="text-[10px] font-black text-(--text-primary) uppercase tracking-widest">Local Grid (30x30m)</span>
        </div>
        <div class="space-y-1">
          <div class="flex justify-between gap-4">
            <span class="text-[10px] text-(--text-secondary) uppercase font-bold">Zoom</span>
            <span class="text-[10px] font-mono text-primary">{{ zoom }} px/m</span>
          </div>
          <div class="flex justify-between gap-4">
            <span class="text-[10px] text-(--text-secondary) uppercase font-bold">X-Offset</span>
            <span class="text-[10px] font-mono text-(--text-primary)">{{ offsetX }}m</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
