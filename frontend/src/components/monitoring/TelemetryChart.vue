<script setup>
import { ref, watch } from 'vue';
import { useVesselStore } from '@/stores/vesselStore';

const vessel = useVesselStore();
const historyData = ref([0, 0, 0, 0, 0, 0, 0, 0, 0, 0]);

watch(() => vessel.sog, (newSog) => {
  historyData.value.push(Number(newSog.toFixed(2)));
  if (historyData.value.length > 20) {
    historyData.value.shift();
  }
}, { immediate: true });

const series = ref([{
  name: 'SOG (Knots)',
  data: historyData
}]);


const chartOptions = ref({
  chart: {
    type: 'area',
    height: 200,
    toolbar: { show: false },
    animations: { enabled: true, easing: 'linear', dynamicAnimation: { speed: 1000 } },
    background: 'transparent',
    sparkline: { enabled: false }
  },
  colors: ['#38bdf8'],
  fill: {
    type: 'gradient',
    gradient: { shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.1, stops: [0, 90, 100] }
  },
  dataLabels: { enabled: false },
  stroke: { curve: 'smooth', width: 3 },
  xaxis: {
    labels: { show: false },
    axisBorder: { show: false },
    axisTicks: { show: false },
    crosshairs: { show: true }
  },
  yaxis: {
    labels: { style: { colors: '#64748b', fontSize: '10px', fontWeight: 'bold' } }
  },
  grid: {
    borderColor: '#1e293b',
    strokeDashArray: 4,
    padding: { top: 10, right: 10, bottom: 0, left: 10 }
  },
  theme: { mode: 'dark' }
});
</script>

<template>
  <div class="glass-card p-4 h-full flex flex-col">
    <div class="flex justify-between items-center mb-4">
       <span class="text-[10px] font-black text-(--text-secondary) uppercase tracking-widest">Historical Telemetry (60s)</span>
       <div class="flex gap-2">
         <span class="text-[10px] font-bold text-primary uppercase">SOG</span>
         <span class="text-[10px] font-bold text-(--text-muted) uppercase">Heading</span>
       </div>
    </div>
    <div class="flex-1 min-h-0">
      <apexchart type="area" height="100%" :options="chartOptions" :series="series"></apexchart>
    </div>
  </div>
</template>
