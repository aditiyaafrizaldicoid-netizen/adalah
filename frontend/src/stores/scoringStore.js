import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { useMissionStore } from "./missionStore";

export const useScoringStore = defineStore("scoring", () => {
  const missionStore = useMissionStore();

  const imh = ref(0); // Image Quality Surface (0, 1, 3, 5)
  const imb = ref(0); // Image Quality Underwater (0, 1, 3, 5)
  const dc = ref(0);  // Docking balls (0, 5, 10, 15)

  // NM calculation based on buoys and other tasks
  const nm = computed(() => {
    // Basic scoring for KKI: buoys passed (up to 10) + imaging + docking
    let score = missionStore.buoysPassed.length; // max 10
    if (missionStore.currentStep > 4) score += 4; // Surface Imaging completion
    if (missionStore.currentStep > 5) score += 3; // Underwater Imaging completion
    if (missionStore.currentStep > 6) score += 3; // Docking completion
    return Math.min(score, 20);
  });

  const nt = computed(() => missionStore.missionElapsedSeconds);
  const p = computed(() => missionStore.penalties * 5); // 5 points per penalty

  const totalScore = computed(() => {
    if (nm.value === 20) {
      // Formula if all tasks completed
      return 100 * ((2 * nm.value - p.value) / nt.value) + imh.value + imb.value + dc.value;
    } else {
      // Formula if tasks incomplete
      return 10 * ((2 * nm.value - p.value) / 900);
    }
  });

  function setImh(val) { imh.value = val; }
  function setImb(val) { imb.value = val; }
  function setDc(val) { dc.value = val; }

  return {
    imh, imb, dc,
    nm, nt, p,
    totalScore,
    setImh, setImb, setDc
  };
});
