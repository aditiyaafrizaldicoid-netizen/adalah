import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { useMissionStore } from "./missionStore";

export const useScoringStore = defineStore("scoring", () => {
  const missionStore = useMissionStore();

  const imh = ref(0); // Image Quality Surface (0, 1, 3, 5)
  const imb = ref(0); // Image Quality Underwater (0, 1, 3, 5)
  const dc = ref(0);  // Docking balls (0, 5, 10, 15)

  // NM calculation based on buoy passes and mission step progress
  const nm = computed(() => {
    // Hitung dari buoyPassCount (berapa gate yang sudah dilewati)
    let score = Math.min(missionStore.buoyPassCount ?? 0, 10); // max 10
    const stepIdx = missionStore.currentStepIdx ?? 0;
    const total = missionStore.totalSteps ?? 0;
    // Bonus poin berdasarkan progress langkah misi
    if (total > 0 && stepIdx > Math.floor(total * 0.6)) score += 4; // past 60%
    if (total > 0 && stepIdx > Math.floor(total * 0.8)) score += 3; // past 80%
    if (missionStore.missionStatus === 'FINISHED') score += 3;
    return Math.min(score, 20);
  });

  const nt = computed(() => Math.max(missionStore.elapsedSec ?? 1, 1)); // avoid div/0
  const p = ref(0); // penalty poin manual, bisa diset dari UI Scoring

  const totalScore = computed(() => {
    const nmVal = nm.value;
    const pVal = p.value;
    const ntVal = nt.value;
    if (nmVal === 20) {
      const raw = 100 * ((2 * nmVal - pVal) / ntVal) + imh.value + imb.value + dc.value;
      return isFinite(raw) ? raw : 0;
    } else {
      return 10 * ((2 * nmVal - pVal) / 900);
    }
  });

  function setImh(val) { imh.value = val; }
  function setImb(val) { imb.value = val; }
  function setDc(val) { dc.value = val; }
  function setPenalty(val) { p.value = val; }

  return {
    imh, imb, dc,
    nm, nt, p,
    totalScore,
    setImh, setImb, setDc, setPenalty
  };
});
