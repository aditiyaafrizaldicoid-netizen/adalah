import { defineStore } from "pinia";
import { ref } from "vue";

export const useSessionStore = defineStore("session", () => {
  const sessions = ref([]);
  const activeSession = ref(null);
  const isRecording = ref(false);

  function startRecording() {
    isRecording.value = true;
    activeSession.value = {
      id: Date.now(),
      startTime: new Date(),
      data: []
    };
  }

  function stopRecording() {
    isRecording.value = false;
    if (activeSession.value) {
      sessions.value.push(activeSession.value);
    }
  }

  return { sessions, activeSession, isRecording, startRecording, stopRecording };
});
