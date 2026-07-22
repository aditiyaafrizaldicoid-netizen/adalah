import { defineStore } from "pinia";
import { ref } from "vue";
import { useVesselStore } from "./vesselStore";
import { useMissionStore } from "./missionStore";

export const useWebsocketStore = defineStore("websocket", () => {
  const vesselStore = useVesselStore();
  const missionStore = useMissionStore();

  const socket = ref(null);
  const status = ref("DISCONNECTED"); // CONNECTED, CONNECTING, DISCONNECTED, ERROR
  const latency = ref(0);
  const lastMessage = ref(null);
  const autoReconnect = ref(true);

  let pingInterval = null;
  let _url = null;

  function connect(url = "ws://localhost:3000/api/v1/ws/client") {
    _url = url;
    status.value = "CONNECTING";

    try {
      socket.value = new WebSocket(url);

      socket.value.onopen = () => {
        status.value = "CONNECTED";
        startPing();

        // Minta sync channel config saat pertama kali konek
        // (Lazy import untuk hindari circular dependency)
        import("./channelConfigStore").then(({ useChannelConfigStore }) => {
          useChannelConfigStore().requestSync();
        });
      };

      socket.value.onmessage = (event) => {
        const data = JSON.parse(event.data);
        lastMessage.value = data;

        if (data.type === "TELEMETRY") {
          vesselStore.updateTelemetry(data.payload);
        } else if (data.type === "RECORDING_STATUS") {
          if (data.payload) {
            vesselStore.isRecording = !!data.payload.is_recording;
            vesselStore.recordingFilename = data.payload.filename || '';
            if (data.payload.width && data.payload.height) {
              vesselStore.recordingResolution = `${data.payload.width}x${data.payload.height}`;
            }
          }
        } else if (data.type === "MISSION_UPDATE") {
          // Update mission state
        } else if (data.type === "PONG") {
          latency.value = Date.now() - data.timestamp;
        } else if (data.type === "CHANNEL_CONFIG") {
          // Sinkronisasi channel config dari ASV
          import("./channelConfigStore").then(({ useChannelConfigStore }) => {
            useChannelConfigStore().updateFromPayload(data.payload);
          });
        }
      };

      socket.value.onclose = () => {
        status.value = "DISCONNECTED";
        stopPing();
        if (autoReconnect.value) {
          setTimeout(() => connect(_url), 3000);
        }
      };

      socket.value.onerror = (err) => {
        status.value = "ERROR";
        console.error("WS Error:", err);
      };
    } catch (e) {
      status.value = "ERROR";
    }
  }

  function startPing() {
    pingInterval = setInterval(() => {
      if (socket.value && status.value === "CONNECTED") {
        socket.value.send(JSON.stringify({ type: "PING", timestamp: Date.now() }));
      }
    }, 1000);
  }

  function stopPing() {
    if (pingInterval) clearInterval(pingInterval);
  }

  /**
   * Kirim perintah ke ASV.
   * Format standar: { type: "COMMAND", cmd: { action, ...params }, timestamp }
   *
   * Contoh:
   *   sendCommand({ action: "arm" })
   *   sendCommand({ action: "set_mode", mode: "MANUAL" })
   *   sendCommand({ action: "drive_vectored", throttle_left: 1600, throttle_right: 1600, servo_left: 1500, servo_right: 1500 })
   *   sendCommand({ action: "set_channel_map", channel_map: { thruster_left_ch: 1, ... } })
   */
  function sendCommand(cmd) {
    if (socket.value && status.value === "CONNECTED") {
      const message = {
        type: "COMMAND",
        cmd,
        timestamp: Date.now(),
      };
      socket.value.send(JSON.stringify(message));
    } else {
      console.warn("[WS] Cannot send: not connected");
    }
  }

  function startRecording(width, height) {
    const cmd = { action: "start_recording" };
    if (width) cmd.width = parseInt(width);
    if (height) cmd.height = parseInt(height);
    sendCommand(cmd);
  }

  function stopRecording() {
    sendCommand({ action: "stop_recording" });
  }

  function toggleRecording(width, height) {
    if (vesselStore.isRecording) {
      stopRecording();
    } else {
      startRecording(width, height);
    }
  }

  function disconnect() {
    autoReconnect.value = false;
    if (socket.value) socket.value.close();
  }

  return {
    socket, status, latency, lastMessage, autoReconnect,
    connect, disconnect, sendCommand, startRecording, stopRecording, toggleRecording,
  };
});
