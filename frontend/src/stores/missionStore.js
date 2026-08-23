import { defineStore } from "pinia";
import { ref, computed, onMounted } from "vue";
import { useWebsocketStore } from "./websocketStore";

// ─── Step Type Definitions ───────────────────────────────────────────────────
export const STEP_TYPES = [
  {
    type: "START",
    label: "Start / Warmup",
    icon: "⚡",
    color: "text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-500/30",
    fields: [{ key: "duration_sec", label: "Warmup Duration (s)", type: "number", default: 2 }],
  },
  {
    type: "TRACKING_BUOY",
    label: "Tracking Buoy (AI Vision)",
    icon: "🎯",
    color: "text-primary",
    bg: "bg-primary/10 border-primary/30",
    fields: [
      { key: "pass_count", label: "Gate Pass Count", type: "number", default: 1 },
      { key: "throttle", label: "Throttle (0-1)", type: "number", default: 0.4 },
      {
        key: "locked_timeout_area_growth_min_ratio",
        label: "Locked-Timeout Auto-Count Growth (x)",
        type: "number",
        default: 1.5,
        // Kalau kapal LOCKED >8 detik pada pasangan yang sama (kedua bola tidak
        // pernah hilang dari frame), dan area pasangan sudah membesar sebesar
        // rasio ini sejak lock pertama, dihitung sebagai 1 pass otomatis —
        // bukti kapal sudah mendekat/lewat, bukan cuma diam menatap gerbang.
      },
    ],
  },
  {
    type: "GOTO_GPS",
    label: "Go To GPS Coordinate",
    icon: "🧭",
    color: "text-sky-400",
    bg: "bg-sky-500/10 border-sky-500/30",
    fields: [
      { key: "lat", label: "Latitude", type: "number", default: -7.9215169 },
      { key: "lon", label: "Longitude", type: "number", default: 112.5973649 },
    ],
  },
  {
    type: "TAKE_IMAGE",
    label: "Take Image / Record",
    icon: "📷",
    color: "text-violet-400",
    bg: "bg-violet-500/10 border-violet-500/30",
    fields: [{ key: "duration_sec", label: "Duration (s)", type: "number", default: 3 }],
  },
  {
    type: "HOLD",
    label: "Hold Position",
    icon: "⚓",
    color: "text-amber-400",
    bg: "bg-amber-500/10 border-amber-500/30",
    fields: [{ key: "duration_sec", label: "Hold Duration (s)", type: "number", default: 5 }],
  },
  // ── Dynamic Movement Steps ──────────────────────────────────────────────
  {
    type: "CUSTOM_FORWARD",
    label: "Custom Forward (Dynamic)",
    icon: "🚀",
    color: "text-cyan-400",
    bg: "bg-cyan-500/10 border-cyan-500/30",
    fields: [
      {
        key: "heading_offset_deg",
        label: "Heading Offset (°)",
        type: "number",
        default: 0,
        // Sudut kemiringan arah gerak dari haluan kapal.
        // 0 = maju lurus, +N = condong kanan N°/s, -N = condong kiri N°/s.
        // Digunakan sebagai yaw rate konstan (°/s) oleh mission_engine saat send_velocity.
      },
      {
        key: "duration_sec",
        label: "Duration (s)",
        type: "number",
        default: 5,
        // Batas waktu kapal menjalankan misi maju ini (dalam detik).
        // Engine akan advance_step() saat elapsed >= duration_sec.
      },
      {
        key: "speed_mps",
        label: "Speed (m/s)",
        type: "number",
        default: 0.5,
        // Kecepatan maju kapal dalam meter per detik.
        // Dikirim sebagai forward_speed ke NavigationControl.send_velocity().
      },
    ],
  },
  {
    type: "GYRO_FORWARD",
    label: "Gyro Forward (Heading Hold)",
    icon: "🌀",
    color: "text-indigo-400",
    bg: "bg-indigo-500/10 border-indigo-500/30",
    fields: [
      {
        key: "throttle",
        label: "Throttle (0-1)",
        type: "number",
        default: 0.4,
        // Sama seperti TRACKING_BUOY: mode MANUAL, gerak via RC Override. Kosongkan
        // untuk fallback ke throttle global (speed_scheduler.max_base_throttle).
      },
      {
        key: "duration_sec",
        label: "Max Duration (s)",
        type: "number",
        default: 15,
        // Batas waktu MAKSIMUM cruise (safety cap). Step berhenti lebih awal begitu
        // buoy (merah/hijau) terdeteksi kontinu di kamera, mana pun yang lebih dulu.
      },
      {
        key: "min_runtime_sec",
        label: "Min Runtime Before Buoy-Stop (s)",
        type: "number",
        default: 1.5,
        // Deteksi buoy diabaikan sampai kapal sudah maju minimal sekian detik —
        // mencegah step langsung selesai kalau buoy/false-positive kebetulan sudah
        // kelihatan tepat saat step baru mulai (kapal belum sempat maju sama sekali).
      },
      {
        key: "heading_kp",
        label: "Heading Correction Kp",
        type: "number",
        default: 0.03,
        // Gain proporsional: steer_norm (-1..+1) per derajat error heading.
        // Heading target = heading kapal saat step ini dimulai (heading-hold).
      },
      {
        key: "heading_deadzone_deg",
        label: "Heading Deadzone (°)",
        type: "number",
        default: 2,
        // Error heading di bawah nilai ini dianggap lurus — tidak ada koreksi,
        // mencegah kapal bergetar akibat micro-correction.
      },
    ],
  },
  {
    type: "PRECISION_TURN",
    label: "Precision Turning",
    icon: "🔄",
    color: "text-orange-400",
    bg: "bg-orange-500/10 border-orange-500/30",
    fields: [
      {
        key: "turn_angle_deg",
        label: "Turn Angle (°)",
        type: "number",
        default: 90,
        // Sudut total belok yang harus ditempuh kapal.
        // +90 = belok kanan 90°, -90 = belok kiri 90°.
        // Engine menghitung target_heading = initial_heading + turn_angle_deg.
      },
      {
        key: "turn_rate_dps",
        label: "Turn Rate (°/s)",
        type: "number",
        default: 20,
        // Kecepatan rotasi dalam derajat per detik.
        // Dikirim sebagai turn_rate_deg ke NavigationControl.send_velocity() selama maneuver.
      },
    ],
  },
  {
    type: "TIMED_STEER",
    label: "Timed Steer (Manual Mode)",
    icon: "⏱️",
    color: "text-rose-400",
    bg: "bg-rose-500/10 border-rose-500/30",
    fields: [
      {
        key: "steer",
        label: "Steering (-1 kiri, 0 lurus, +1 kanan)",
        type: "number",
        default: 0,
      },
      {
        key: "throttle",
        label: "Throttle (0-1)",
        type: "number",
        default: 0.3,
      },
      {
        key: "duration_sec",
        label: "Duration (s)",
        type: "number",
        default: 3,
      },
    ],
  },
  // ── Sequential Multi-Pair Buoy ─────────────────────────────────────────
  // Tidak ada field konfigurasi jumlah pasangan — engine berjalan otomatis
  // sampai tidak ada lagi pasangan buoy (merah+hijau) yang terdeteksi di frame.
  // Pasangan diurutkan otomatis: yang paling dekat kamera = Pasangan 1.
  // Engine: SEARCHING → LOCKED → TRANSITIONING → CLEARED, lalu lanjut pasangan berikutnya.
  {
    type: "SEQUENTIAL_BUOY",
    label: "Sequential Buoy (Multi-Pair)",
    icon: "🛟",
    color: "text-teal-400",
    bg: "bg-teal-500/10 border-teal-500/30",
    fields: [
      { key: "throttle", label: "Throttle (0-1)", type: "number", default: 0.4 },
      {
        key: "ignore_area_px2",
        label: "Ignore Below Area (px²)",
        type: "number",
        default: 2020,
        // Pasangan bola dengan area rata-rata bounding box di bawah nilai ini
        // dianggap TIDAK ADA sama sekali (bukan sekadar "belum boleh dikunci") —
        // tidak dikejar maupun dikunci. Ini yang membuat step bisa SELESAI walau
        // ada deteksi bola yang sangat jauh (course lain, noise, dst).
      },
      {
        key: "no_detection_finish_sec",
        label: "Finish After No Detection (s)",
        type: "number",
        default: 15,
        // Kalau BENAR-BENAR tidak ada apa pun terdeteksi (tidak ada kandidat
        // pasangan maupun fallback gate_x) selama durasi ini, step dianggap
        // SELESAI dan lanjut ke step berikutnya — bukan cuma berhenti bergerak.
        // Berlaku sejak awal step, tidak peduli sudah ada pasangan yang cleared
        // atau belum.
      },
      {
        key: "single_ball_clearance_px",
        label: "Single-Ball Clearance (px)",
        type: "number",
        default: 205,
        // Saat cuma 1 warna bola terdeteksi (pairing gagal total), kapal menjaga
        // jarak bola ini ke tengah frame minimal sebesar ini — bukan mengejar
        // posisinya. Di bawah jarak ini koreksi menjauh mulai diterapkan.
      },
      {
        key: "single_ball_max_steer",
        label: "Single-Ball Max Steer (0-1)",
        type: "number",
        default: 0.4,
        // Steer maksimum koreksi jaga-jarak bola tunggal, dicapai saat bola
        // tepat di tengah frame (paling bahaya).
      },
      {
        key: "locked_timeout_area_growth_min_ratio",
        label: "Locked-Timeout Auto-Count Growth (x)",
        type: "number",
        default: 1.5,
        // Kalau kapal LOCKED >8 detik pada pasangan yang sama (kedua bola tidak
        // pernah hilang dari frame), dan area pasangan sudah membesar sebesar
        // rasio ini sejak lock pertama, dihitung sebagai 1 pasangan cleared
        // otomatis — bukti kapal sudah mendekat/lewat, bukan cuma diam.
      },
    ],
  },
  {
    type: "FINISH",
    label: "Mission Complete",
    icon: "🏁",
    color: "text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-500/30",
    fields: [],
  },
];

export const getStepTypeDef = (type) => STEP_TYPES.find((s) => s.type === type) || null;

// ─── Mission Store ────────────────────────────────────────────────────────────
export const useMissionStore = defineStore("mission", () => {
  // Mission pipeline steps (user-defined)
  const steps = ref([]);

  // Live mission status from backend
  const missionStatus = ref("IDLE");    // IDLE, RUNNING, PAUSED, FINISHED, ABORTED
  const currentStepIdx = ref(0);
  const currentStep = ref({});
  const totalSteps = ref(0);
  const elapsedSec = ref(0);
  const buoyPassCount = ref(0);

  // Sequential Buoy live state (sync dari MISSION_STATUS payload)
  const seqPairsCleared = ref(0);  // berapa pasang buoy yang sudah berhasil dilewati
  const seqCurrentPair  = ref(1);  // pasangan yang sedang diincar (1-indexed)

  // Legacy (for timeline component compatibility)
  const currentStep_legacy = ref(1);
  const missionElapsedSeconds = ref(0);
  const waypoints = ref([]);

  // ─── Waypoint Management ──────────────────────────────────────────────────
  function addWaypoint(lat, lng) {
    waypoints.value.push({ lat, lng });
  }

  function removeWaypoint(index) {
    waypoints.value.splice(index, 1);
  }

  function clearWaypoints() {
    waypoints.value = [];
  }

  // Konversi waypoints ke GOTO_GPS steps dan sisipkan ke pipeline misi.
  // Jika sudah ada step dengan tipe GOTO_GPS, mereka digantikan;
  // jika tidak ada, waypoints disisipkan sebelum step FINISH (atau di akhir).
  function loadWaypointsAsMission() {
    if (!waypoints.value.length) return;
    const gotoSteps = waypoints.value.map((wp, i) => ({
      id: Date.now() + i,
      type: 'GOTO_GPS',
      name: `Waypoint ${(i + 1).toString().padStart(2, '0')}`,
      lat: parseFloat(wp.lat.toFixed(7)),
      lon: parseFloat(wp.lng.toFixed(7)),
    }));
    // Hapus step GOTO_GPS yang sudah ada, sisipkan yang baru sebelum FINISH
    const nonGoto = steps.value.filter(s => s.type !== 'GOTO_GPS');
    const finishIdx = nonGoto.findIndex(s => s.type === 'FINISH');
    if (finishIdx !== -1) {
      nonGoto.splice(finishIdx, 0, ...gotoSteps);
    } else {
      nonGoto.push(...gotoSteps);
    }
    steps.value = nonGoto;
    console.log(`[MissionStore] Loaded ${gotoSteps.length} waypoints as GOTO_GPS steps.`);
  }

  // Timer for UI elapsed counter
  let _timerInterval = null;

  // Formatted time
  const formattedTime = computed(() => {
    const t = elapsedSec.value;
    const m = Math.floor(t / 60).toString().padStart(2, "0");
    const s = (t % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  });

  const stepElapsedSec = ref(0);

  // Dynamic Progress Calculations
  const progressPct = computed(() => {
    if (missionStatus.value === "FINISHED") return 100;
    const total = totalSteps.value || steps.value.length;
    if (!total || missionStatus.value === "IDLE") return 0;

    let baseRatio = currentStepIdx.value / total;

    if (missionStatus.value === "RUNNING" || missionStatus.value === "PAUSED") {
      const step = currentStep.value?.type ? currentStep.value : steps.value[currentStepIdx.value];
      let subRatio = 0;

      if (step) {
        if (step.type === "TRACKING_BUOY" && step.pass_count > 0) {
          subRatio = Math.min(buoyPassCount.value / step.pass_count, 1.0);
        } else if (step.duration_sec && step.duration_sec > 0) {
          subRatio = Math.min(stepElapsedSec.value / step.duration_sec, 1.0);
        }
      }

      baseRatio += subRatio / total;
    }

    return Math.min(100, Math.round(baseRatio * 100));
  });

  const activeStepLabel = computed(() => {
    if (missionStatus.value === "FINISHED") return "Mission Complete";
    if (missionStatus.value === "IDLE") {
      const total = steps.value.length;
      if (!total) return "No Steps Configured";
      return `Ready (${total} Steps)`;
    }
    if (missionStatus.value === "ABORTED") return "Mission Aborted";

    const step = currentStep.value?.type ? currentStep.value : steps.value[currentStepIdx.value];
    if (!step) return `Step ${currentStepIdx.value + 1}`;

    const stepNum = (currentStepIdx.value + 1).toString().padStart(2, '0');
    const totalNum = (totalSteps.value || steps.value.length).toString().padStart(2, '0');

    if (step.type === "START") {
      const remaining = Math.max(0, Math.ceil((step.duration_sec || 2) - stepElapsedSec.value));
      return `[${stepNum}/${totalNum}] Warmup (${remaining}s)`;
    }

    if (step.type === "TRACKING_BUOY") {
      const passTarget = step.pass_count || 1;
      const passed = buoyPassCount.value || 0;
      return `[${stepNum}/${totalNum}] Buoy Gate ${passed}/${passTarget}`;
    }

    if (step.type === "SEQUENTIAL_BUOY") {
      const pairDone = seqPairsCleared.value || 0;
      return `[${stepNum}/${totalNum}] Sequential Buoy — Pair ${seqCurrentPair.value} (${pairDone} cleared)`;
    }

    if (step.duration_sec) {
      const remaining = Math.max(0, Math.ceil(step.duration_sec - stepElapsedSec.value));
      return `[${stepNum}/${totalNum}] ${step.name || step.type} (${remaining}s)`;
    }

    return `[${stepNum}/${totalNum}] ${step.name || step.type}`;
  });


  // ─── Step Builder Actions ─────────────────────────────────────────────────
  function addStep(type) {
    const def = getStepTypeDef(type);
    if (!def) return;
    const defaults = {};
    def.fields.forEach((f) => (defaults[f.key] = f.default));
    steps.value.push({
      id: Date.now(),
      type,
      name: def.label,
      ...defaults,
    });
  }

  function removeStep(index) {
    steps.value.splice(index, 1);
  }

  function moveStep(fromIdx, toIdx) {
    if (toIdx < 0 || toIdx >= steps.value.length) return;
    const arr = [...steps.value];
    const [item] = arr.splice(fromIdx, 1);
    arr.splice(toIdx, 0, item);
    steps.value = arr;
  }

  function updateStep(index, key, value) {
    if (steps.value[index]) {
      steps.value[index][key] = value;
    }
  }

  function clearSteps() {
    steps.value = [];
  }

  // ─── WebSocket Mission Commands ───────────────────────────────────────────
  function loadAndStartMission() {
    if (!steps.value.length) return;
    const wsStore = useWebsocketStore();
    const stepsPayload = steps.value.map((s, i) => ({ ...s, id: i + 1 }));

    wsStore.sendCommand({ action: "arm" });
    wsStore.sendCommand({ action: "set_mode", mode: "GUIDED" });
    wsStore.sendCommand({ action: "start_mission", steps: stepsPayload });
  }

  function startMission() {
    if (!steps.value.length) return;
    const wsStore = useWebsocketStore();
    const stepsPayload = steps.value.map((s, i) => ({ ...s, id: i + 1 }));

    wsStore.sendCommand({ action: "arm" });
    wsStore.sendCommand({ action: "set_mode", mode: "GUIDED" });
    wsStore.sendCommand({ action: "start_mission", steps: stepsPayload });
    missionStatus.value = "RUNNING";
    _startLocalTimer();
  }



  function pauseMission() {
    const wsStore = useWebsocketStore();
    wsStore.sendCommand({ action: "pause_mission" });
    missionStatus.value = "PAUSED";
    _stopLocalTimer();
  }

  function resumeMission() {
    const wsStore = useWebsocketStore();
    wsStore.sendCommand({ action: "resume_mission" });
    missionStatus.value = "RUNNING";
    _startLocalTimer();
  }

  function abortMission() {
    const wsStore = useWebsocketStore();
    wsStore.sendCommand({ action: "abort_mission" });
    missionStatus.value = "ABORTED";
    _stopLocalTimer();
  }

  function resetMission() {
    const wsStore = useWebsocketStore();
    wsStore.sendCommand({ action: "reset_mission" });
    missionStatus.value = "IDLE";
    currentStepIdx.value = 0;
    elapsedSec.value = 0;
    buoyPassCount.value = 0;
    _stopLocalTimer();
  }

  // ─── Live Status Update from WS ──────────────────────────────────────────
  function updateMissionStatus(payload) {
    missionStatus.value = payload.status || "IDLE";
    currentStepIdx.value = payload.current_step_idx ?? 0;
    currentStep.value = payload.current_step ?? {};
    totalSteps.value = payload.total_steps ?? 0;
    stepElapsedSec.value = payload.step_elapsed_sec ?? 0;
    buoyPassCount.value = payload.buoy_pass_count ?? 0;
    currentStep_legacy.value = (payload.current_step_idx ?? 0) + 1;

    // Sequential Buoy live state — dikirim oleh MissionEngine.get_status_dict()
    seqPairsCleared.value = payload.seq_pairs_cleared ?? 0;
    seqCurrentPair.value  = payload.seq_current_pair  ?? 1;

    if (missionStatus.value === "RUNNING" && !_timerInterval) {
      _startLocalTimer();
    } else if (missionStatus.value !== "RUNNING") {
      _stopLocalTimer();
    }
  }

  // ─── Presets & Database Persistence ───────────────────────────────────────
  const dbPresets = ref([]);

  const presets = computed(() => dbPresets.value);

  async function fetchPresets() {
    try {
      const res = await fetch("http://localhost:3000/api/v1/mission-presets");
      if (res.ok) {
        const json = await res.json();
        if (json.status === "success" && Array.isArray(json.data)) {
          dbPresets.value = json.data.map((item) => {
            let parsedSteps = [];
            try {
              parsedSteps = typeof item.steps === "string" ? JSON.parse(item.steps) : item.steps;
            } catch (e) {
              parsedSteps = [];
            }
            return {
              id: `db_${item.id}`,
              dbId: item.id,
              name: item.name,
              steps: parsedSteps,
              isDb: true,
            };
          });
        }
      }
    } catch (e) {
      console.warn("[MissionStore] Failed to fetch presets from database:", e);
    }
  }

  async function saveCurrentAsPreset(presetName) {
    if (!steps.value.length) return false;
    const name = presetName || `Mission ${new Date().toLocaleString('id-ID')}`;
    try {
      const res = await fetch("http://localhost:3000/api/v1/mission-presets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name,
          steps: JSON.stringify(steps.value),
        }),
      });
      if (res.ok) {
        await fetchPresets();
        return true;
      }
    } catch (e) {
      console.error("[MissionStore] Failed to save preset to database:", e);
    }
    return false;
  }

  async function deletePreset(dbId) {
    try {
      const res = await fetch(`http://localhost:3000/api/v1/mission-presets/${dbId}`, {
        method: "DELETE",
      });
      if (res.ok) {
        await fetchPresets();
        return true;
      }
    } catch (e) {
      console.error("[MissionStore] Failed to delete preset:", e);
    }
    return false;
  }

  function loadPreset(preset) {
    steps.value = preset.steps.map((s) => ({ ...s, id: Date.now() + Math.random() }));
  }

  // Fetch presets from DB on init; steps mulai kosong
  fetchPresets();


  // ─── Internal ─────────────────────────────────────────────────────────────
  function _startLocalTimer() {
    if (_timerInterval) return;
    _timerInterval = setInterval(() => {
      elapsedSec.value++;
    }, 1000);
  }

  function _stopLocalTimer() {
    if (_timerInterval) {
      clearInterval(_timerInterval);
      _timerInterval = null;
    }
  }

  // Legacy compat
  const missionSteps = computed(() =>
    steps.value.map((s, i) => ({ id: i + 1, name: s.name || s.type }))
  );

  return {
    // State
    steps, missionStatus, currentStepIdx, currentStep, totalSteps,
    elapsedSec, buoyPassCount, formattedTime, progressPct, activeStepLabel, waypoints, presets, dbPresets,
    // Sequential Buoy live state
    seqPairsCleared, seqCurrentPair,
    // Legacy
    missionSteps, currentStep_legacy,
    // Step builder
    addStep, removeStep, moveStep, updateStep, clearSteps,
    // Mission control
    startMission, pauseMission, resumeMission, abortMission, resetMission, loadAndStartMission,
    // Status updater
    updateMissionStatus,
    // Presets & Database
    loadPreset, fetchPresets, saveCurrentAsPreset, deletePreset,
    // Waypoints
    addWaypoint, removeWaypoint, clearWaypoints, loadWaypointsAsMission, stepElapsedSec
  };
});
