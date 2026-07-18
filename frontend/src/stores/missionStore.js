import { defineStore } from "pinia";
import { ref, computed } from "vue";

export const useMissionStore = defineStore("mission", () => {
  const currentStep = ref(1);
  const buoysPassed = ref([]);
  const penalties = ref(0);
  const missionStatus = ref("IDLE"); // IDLE, RUNNING, PAUSED, FINISHED, ABORTED
  const missionStartTime = ref(null);
  const waypoints = ref([]);

  const missionElapsedSeconds = ref(0);
  let timerInterval = null;

  const missionSteps = [
    { id: 1, name: "Preparation" },
    { id: 2, name: "Start" },
    { id: 3, name: "Buoy 1-10 Navigation" },
    { id: 4, name: "Surface Imaging" },
    { id: 5, name: "Underwater Imaging" },
    { id: 6, name: "Docking" },
    { id: 7, name: "Finish" }
  ];

  const formattedTime = computed(() => {
    const mins = Math.floor(missionElapsedSeconds.value / 60);
    const secs = missionElapsedSeconds.value % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  });

  function startMission() {
    missionStatus.value = "RUNNING";
    missionStartTime.value = Date.now();
    missionElapsedSeconds.value = 0;
    
    if (timerInterval) clearInterval(timerInterval);
    timerInterval = setInterval(() => {
      missionElapsedSeconds.value++;
    }, 1000);
  }

  function pauseMission() {
    missionStatus.value = "PAUSED";
    if (timerInterval) clearInterval(timerInterval);
  }

  function resumeMission() {
    missionStatus.value = "RUNNING";
    timerInterval = setInterval(() => {
      missionElapsedSeconds.value++;
    }, 1000);
  }

  function stopMission() {
    missionStatus.value = "FINISHED";
    if (timerInterval) clearInterval(timerInterval);
  }

  function resetMission() {
    missionStatus.value = "IDLE";
    currentStep.value = 1;
    buoysPassed.value = [];
    penalties.value = 0;
    missionElapsedSeconds.value = 0;
    if (timerInterval) clearInterval(timerInterval);
  }

  return {
    currentStep,
    buoysPassed,
    penalties,
    missionStatus,
    missionStartTime,
    waypoints,
    missionSteps,
    missionElapsedSeconds,
    formattedTime,
    startMission,
    pauseMission,
    resumeMission,
    stopMission,
    resetMission
  };
});
