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
  // Status kalibrasi IMU: { step, progress, message, success, failed, error }
  const imuCalibrationStatus = ref(null);

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
        } else if (data.type === "STREAMING_STATUS") {
          // ACK dari ASV setelah streaming ON/OFF berhasil dijalankan
          if (data.payload && data.payload.is_streaming !== undefined) {
            vesselStore.isStreaming = data.payload.is_streaming;
          }
        } else if (data.type === "MISSION_UPDATE") {
          // Legacy mission update
        } else if (data.type === "MISSION_STATUS") {
          // Live mission engine status from Mini PC
          import("./missionStore").then(({ useMissionStore }) => {
            useMissionStore().updateMissionStatus(data.payload);
          });
        } else if (data.type === "PONG") {

          latency.value = Date.now() - data.timestamp;
        } else if (data.type === "CHANNEL_CONFIG") {
          // Sinkronisasi channel config dari ASV
          import("./channelConfigStore").then(({ useChannelConfigStore }) => {
            useChannelConfigStore().updateFromPayload(data.payload);
          });
        } else if (data.type === "IMU_CALIBRATION_STATUS") {
          imuCalibrationStatus.value = data.payload;
        } else if (data.type === "WARNING") {
          // Warning dari backend (ASV disconnect, FC disconnect, dll)
          const p = data.payload;
          if (p) {
            vesselStore.addWarning(p.level, p.code, p.message);
            // Update state koneksi ASV & kamera berdasarkan kode warning
            if (p.code === "ASV_CONNECTED") {
              vesselStore.asvConnected = true;
              vesselStore.clearWarning("ASV_DISCONNECTED");
              vesselStore.clearWarning("ASV_OFFLINE");
            } else if (p.code === "ASV_DISCONNECTED" || p.code === "ASV_OFFLINE") {
              vesselStore.asvConnected = false;
            } else if (p.code === "CAMERA_LOST") {
              vesselStore.cameraConnected = false;
            } else if (p.code === "CAMERA_RESTORED") {
              vesselStore.cameraConnected = true;
              vesselStore.clearWarning("CAMERA_LOST");
            }

          }
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

  function saveCurrentWaypoint() {
    sendCommand({ action: "save_current_waypoint" });
  }

  function uploadMission(waypoints) {
    sendCommand({ action: "upload_mission", waypoints });
  }

  /**
   * Kirim pipeline misi (array of step objects) ke Python flight controller.
   * Python akan me-load steps ke MissionEngine tanpa langsung start.
   * Setelah berhasil, Python membalas dengan MISSION_STATUS → missionStore.updateMissionStatus().
   * @param {Array} steps - Array step dari missionStore.steps
   * @returns {boolean} true jika berhasil terkirim (WS connected), false jika tidak
   */
  function loadMissionToASV(steps) {
    if (!steps || !steps.length) return false;
    sendCommand({ action: "load_mission", steps });
    return status.value === "CONNECTED";
  }

  function setRelativeWaypoints(meterWaypoints) {
    sendCommand({ action: "set_relative_waypoints", meter_waypoints: meterWaypoints });
  }

  function updatePid(params) {
    sendCommand({
      action: "update_pid",
      kp: params.kp !== undefined ? parseFloat(params.kp) : undefined,
      ki: params.ki !== undefined ? parseFloat(params.ki) : undefined,
      kd: params.kd !== undefined ? parseFloat(params.kd) : undefined,
      forward_speed: params.forward_speed !== undefined ? parseFloat(params.forward_speed) : undefined,
      max_turn_rate: params.max_turn_rate !== undefined ? parseFloat(params.max_turn_rate) : undefined,
      align_threshold_px: params.align_threshold_px !== undefined ? parseFloat(params.align_threshold_px) : undefined,
    });
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

  // ── Streaming ON/OFF ────────────────────────────────────────────────────

  function startStreaming() {
    sendCommand({ action: "start_streaming" });
  }

  function stopStreaming() {
    sendCommand({ action: "stop_streaming" });
  }

  /** Toggle streaming: matikan jika sedang ON, nyalakan jika sedang OFF. */
  function toggleStreaming() {
    if (vesselStore.isStreaming) {
      stopStreaming();
    } else {
      startStreaming();
    }
  }

  function disconnect() {
    autoReconnect.value = false;

    if (socket.value) socket.value.close();
  }

  return {
    socket, status, latency, lastMessage, autoReconnect,
    imuCalibrationStatus,
    connect, disconnect, sendCommand,
    startRecording, stopRecording, toggleRecording,
    startStreaming, stopStreaming, toggleStreaming,
    saveCurrentWaypoint, uploadMission, loadMissionToASV, setRelativeWaypoints, updatePid,
  };
});


