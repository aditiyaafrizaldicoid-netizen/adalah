"""
MissionEngine - Autonomous Mission Sequence Executor untuk ASV.

Engine ini mengeksekusi mission steps secara berurutan:
- TRACKING_BUOY  : AI Vision PID untuk melewati gerbang bola hijau+merah
- GOTO_GPS       : Navigasi ke koordinat GPS tertentu
- TAKE_IMAGE     : Berhenti dan ambil foto/rekam video
- HOLD           : Berhenti di posisi saat ini
- FINISH         : Selesaikan misi dan tahan posisi

Format Mission Steps (JSON array):
[
    { "id": 1, "type": "TRACKING_BUOY", "name": "Gate 1-10",  "pass_count": 5 },
    { "id": 2, "type": "GOTO_GPS",      "name": "Waypoint A", "lat": -7.921, "lon": 112.597 },
    { "id": 3, "type": "TAKE_IMAGE",    "name": "Foto Spot",  "duration_sec": 3.0 },
    { "id": 4, "type": "FINISH",        "name": "Mission End" }
]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gate Locking & Transition Maneuver — State Machine

SEARCHING → LOCKED → TRANSITIONING → CLEARED → buoy_pass_count += 1 → SEARCHING

  SEARCHING    : Belum ada pasangan bola terlihat. Gunakan fallback gate_x dari tracker.
  LOCKED       : Kedua bola (merah+hijau) terlihat bersamaan. Kunci pasangan ini, PID ke midpoint.
  TRANSITIONING: Satu bola hilang saat LOCKED. Manuver condong ke arah bola yang hilang.
                 DILARANG memasangkan bola tersisa dengan bola dari gerbang berikutnya.
  CLEARED      : Bola tersisa juga hilang. Gate dinyatakan terlewati. Reset ke SEARCHING.

Aturan lean saat TRANSITIONING:
  - Bola kiri (merah) hilang duluan → kapal condong ke KIRI  (steer negatif)
  - Bola kanan (hijau) hilang duluan → kapal condong ke KANAN (steer positif)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import time
import math
import threading
from typing import Optional, List, Dict, Any, Tuple


from control.speed_scheduler import SpeedScheduler


class MissionEngine:
    """
    Finite State Machine untuk mengeksekusi mission steps otonom.

    Menggunakan Steering Normalized & SpeedScheduler Throttle Ratio
    untuk kendali AI pada mode MANUAL via RC Override.
    """

    STATUS_IDLE       = "IDLE"
    STATUS_RUNNING    = "RUNNING"
    STATUS_PAUSED     = "PAUSED"
    STATUS_FINISHED   = "FINISHED"
    STATUS_ABORTED    = "ABORTED"

    STEP_TYPE_TRACKING_BUOY  = "TRACKING_BUOY"
    STEP_TYPE_GOTO_GPS       = "GOTO_GPS"
    STEP_TYPE_TAKE_IMAGE     = "TAKE_IMAGE"
    STEP_TYPE_HOLD           = "HOLD"
    STEP_TYPE_FINISH         = "FINISH"
    STEP_TYPE_START          = "START"
    STEP_TYPE_CUSTOM_FORWARD = "CUSTOM_FORWARD"  # Maju lurus/serong dengan heading offset konstan
    STEP_TYPE_PRECISION_TURN = "PRECISION_TURN"  # Belok presisi ke sudut target
    STEP_TYPE_TIMED_STEER    = "TIMED_STEER"     # Manuver timer RC override (MANUAL mode)
    STEP_TYPE_SEQUENTIAL_BUOY = "SEQUENTIAL_BUOY"  # Lewati N pasang buoy (hijau+merah) secara berurutan

    # Radius acceptance untuk GOTO_GPS: dianggap tiba jika < X meter dari target
    ARRIVAL_RADIUS_M = 2.0

    # Threshold heading error untuk PRECISION_TURN: dianggap selesai jika |error| <= X derajat
    TURN_ARRIVAL_THRESHOLD_DEG = 3.0

    # ---- Gate State Machine states ----
    GATE_SEARCHING    = "SEARCHING"
    GATE_LOCKED       = "LOCKED"
    GATE_TRANSITIONING = "TRANSITIONING"
    GATE_CLEARED      = "CLEARED"

    # Normalized steering saat manuver TRANSITIONING (-1..+1).
    # Positif = condong kanan, negatif = condong kiri.
    TRANSITION_LEAN_MAGNITUDE = 0.4

    # Jarak maksimum (piksel) untuk mengenali bola yang sama saat LOCKED/TRANSITIONING.
    # Bola yang lebih jauh dari ini dianggap bola dari gerbang lain dan diabaikan.
    # Nilai 300px (~47% frame 640px) memberi toleransi cukup saat kapal berbelok/bergerak.
    GATE_IDENTITY_MAX_DIST_PX = 300

    # Timeout (detik) maksimum di state LOCKED sebelum di-reset ke SEARCHING.
    # Handle kasus kapal berhenti menghadap gate tapi tidak maju / bola tidak hilang-hilang.
    GATE_LOCKED_TIMEOUT_SEC = 8.0

    # Timeout (detik) maksimum di state TRANSITIONING sebelum dipaksa CLEARED.
    # Handle kasus bola tersisa terus terlihat (kapal tidak maju / false detection).
    GATE_TRANSITIONING_TIMEOUT_SEC = 4.0

    def __init__(self, asv, tracker, tracking_controller, speed_scheduler: Optional[SpeedScheduler] = None):
        self.asv = asv
        self.tracker = tracker
        self.tracking_controller = tracking_controller
        self.speed_scheduler = speed_scheduler or SpeedScheduler(max_base_throttle=0.4)

        self._steps: List[Dict[str, Any]] = []
        self._current_step_idx: int = 0
        self._status: str = self.STATUS_IDLE

        self._lock = threading.RLock()

        # Counter berapa gate PASSING sudah terjadi di step TRACKING saat ini
        self._buoy_pass_count: int = 0

        # ---- Gate State Machine ----
        self._gate_lock_state: str = self.GATE_SEARCHING
        # Posisi bola yang dikunci saat state LOCKED: (cx, cy)
        self._locked_red_pos: Optional[Tuple[int, int]] = None
        self._locked_green_pos: Optional[Tuple[int, int]] = None
        # Sisi bola mana yang hilang duluan saat TRANSITIONING ("left"=merah, "right"=hijau)
        self._missing_side: Optional[str] = None
        # Steer fallback yang dipertahankan selama TRANSITIONING jika bola tersisa tidak terdeteksi
        self._transition_steer: float = 0.0
        # Timestamp saat masuk ke state LOCKED / TRANSITIONING (untuk timeout guard)
        self._gate_state_entered_at: float = 0.0
        # Timestamp saat mission di-pause dalam state LOCKED/TRANSITIONING.
        # Digunakan untuk mengkompensasi durasi pause agar timeout tidak salah tembak saat resume.
        self._gate_pause_start: float = 0.0

        # ---- SEQUENTIAL_BUOY state ----
        # Semua variabel diberi prefix _seq_ agar tidak bersinggungan sama sekali
        # dengan state TRACKING_BUOY (_gate_*) yang sudah ada.
        self._seq_pairs_cleared: int = 0            # Pasangan yang sudah berhasil dilewati
        self._seq_gate_lock_state: str = self.GATE_SEARCHING
        self._seq_locked_red_pos: Optional[Tuple[int, int]] = None
        self._seq_locked_green_pos: Optional[Tuple[int, int]] = None
        self._seq_missing_side: Optional[str] = None
        self._seq_transition_steer: float = 0.0
        self._seq_gate_state_entered_at: float = 0.0
        self._seq_gate_pause_start: float = 0.0

        # Waktu mulai step aktif & offset saat pause
        self._step_start_time: Optional[float] = None
        self._paused_step_elapsed: float = 0.0
        self._last_goto_time: float = 0.0

        # ---- PRECISION_TURN state ----
        # Heading awal (derajat, 0-360) saat step PRECISION_TURN dimulai.
        # Diambil dari telemetry.heading pada frame pertama step ini.
        self._turn_initial_heading: Optional[float] = None

        # Heading target (derajat, 0-360) = _turn_initial_heading + turn_angle_deg (mod 360).
        # Engine terus mengirim yaw rate hingga selisih heading <= TURN_ARRIVAL_THRESHOLD_DEG.
        self._turn_target_heading: Optional[float] = None

        # Callback → kirim status live ke Base Station via WebSocket
        self._status_callback = None

        # Timestamp mulai mission
        self._mission_start_time: Optional[float] = None
        self._elapsed_sec: int = 0

        self._elapsed_thread: Optional[threading.Thread] = None
        self._elapsed_running: bool = False

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def set_status_callback(self, cb):
        """Daftarkan callback fn(status_dict) untuk broadcast status ke WS."""
        self._status_callback = cb

    def load_mission(self, steps: List[Dict[str, Any]]) -> bool:
        """Load mission steps dari JSON array. Return True jika valid."""
        with self._lock:
            if self._status == self.STATUS_RUNNING:
                print("[MissionEngine] Tidak bisa load mission saat RUNNING!")
                return False
            self._steps = list(steps)
            self._current_step_idx = 0
            self._status = self.STATUS_IDLE
            self._buoy_pass_count = 0
            self._reset_gate_state_machine()
            self._reset_sequential_state()
            self._step_start_time = None
            self._paused_step_elapsed = 0.0
            print(f"[MissionEngine] Mission loaded: {len(self._steps)} steps.")
            self._broadcast_status()
            return True

    def start_mission(self, steps: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Mulai eksekusi mission (bisa sekaligus load steps jika diberikan)."""
        with self._lock:
            if steps:
                self._steps = list(steps)
                self._current_step_idx = 0
                self._buoy_pass_count = 0
                self._reset_gate_state_machine()
                self._reset_sequential_state()
                self._step_start_time = None
                self._paused_step_elapsed = 0.0
                print(f"[MissionEngine] Mission loaded: {len(self._steps)} steps.")

            if not self._steps:
                print("[MissionEngine] Tidak ada mission steps yang di-load!")
                return False
            if self._status == self.STATUS_RUNNING:
                print("[MissionEngine] Mission sudah RUNNING!")
                return False

            # Hentikan elapsed timer lama agar tidak ada thread ganda saat restart
            self._stop_elapsed_timer()

            self._status = self.STATUS_RUNNING
            self._current_step_idx = 0
            self._buoy_pass_count = 0
            self._reset_gate_state_machine()
            self._reset_sequential_state()
            self._step_start_time = None
            self._paused_step_elapsed = 0.0
            self._last_goto_time = 0.0
            self._mission_start_time = time.time()
            self._elapsed_sec = 0
            # Reset PRECISION_TURN state agar bisa dipakai ulang dari awal
            self._turn_initial_heading = None
            self._turn_target_heading  = None

            if hasattr(self.tracking_controller, 'reset'):
                self.tracking_controller.reset()

            self._start_elapsed_timer()
            print(f"[MissionEngine]  MISSION STARTED! ({len(self._steps)} steps)")
            self._broadcast_status()
            return True

    def pause_mission(self):
        """Pause mission (ASV berhenti di posisi)."""
        with self._lock:
            if self._status != self.STATUS_RUNNING:
                return
            self._status = self.STATUS_PAUSED
            if self._step_start_time:
                self._paused_step_elapsed += time.time() - self._step_start_time
                self._step_start_time = None
            # Simpan timestamp pause gate timer agar timeout tidak salah tembak saat resume.
            # Tanpa ini, jika paused >8s saat LOCKED maka resume langsung timeout → SEARCHING.
            if (self._gate_lock_state in (self.GATE_LOCKED, self.GATE_TRANSITIONING)
                    and self._gate_state_entered_at > 0):
                self._gate_pause_start = time.time()
            # Kompensasi juga untuk Sequential Buoy gate FSM
            if (self._seq_gate_lock_state in (self.GATE_LOCKED, self.GATE_TRANSITIONING)
                    and self._seq_gate_state_entered_at > 0):
                self._seq_gate_pause_start = time.time()
            self._stop_elapsed_timer()
            self.asv.stop_movement()
            print(f"[MissionEngine] ⏸ MISSION PAUSED (Step elapsed: {self._paused_step_elapsed:.1f}s).")
            self._broadcast_status()

    def resume_mission(self):
        """Resume mission dari paused."""
        with self._lock:
            if self._status != self.STATUS_PAUSED:
                return
            self._status = self.STATUS_RUNNING
            self._step_start_time = time.time() - self._paused_step_elapsed
            # Kompensasi gate timer: geser entered_at maju sebesar durasi pause
            # sehingga timeout dihitung dari waktu aktif saja, bukan termasuk waktu pause.
            if self._gate_pause_start > 0 and self._gate_state_entered_at > 0:
                paused_duration = time.time() - self._gate_pause_start
                self._gate_state_entered_at += paused_duration
                self._gate_pause_start = 0.0
            # Kompensasi juga untuk Sequential Buoy gate FSM
            if self._seq_gate_pause_start > 0 and self._seq_gate_state_entered_at > 0:
                paused_duration = time.time() - self._seq_gate_pause_start
                self._seq_gate_state_entered_at += paused_duration
                self._seq_gate_pause_start = 0.0
            self._start_elapsed_timer()
            print("[MissionEngine]  MISSION RESUMED.")
            self._broadcast_status()

    def abort_mission(self):
        """Batalkan mission dan stop kapal."""
        with self._lock:
            self._status = self.STATUS_ABORTED
            self._stop_elapsed_timer()
            self.asv.stop_movement()
            print("[MissionEngine]  MISSION ABORTED!")
            self._broadcast_status()

    def reset_mission(self):
        """Reset semua state ke IDLE."""
        with self._lock:
            self._status = self.STATUS_IDLE
            self._current_step_idx = 0
            self._buoy_pass_count = 0
            self._step_start_time = None
            self._paused_step_elapsed = 0.0
            self._elapsed_sec = 0
            self._reset_gate_state_machine()
            self._reset_sequential_state()
            # Reset PRECISION_TURN state
            self._turn_initial_heading = None
            self._turn_target_heading  = None
            self._stop_elapsed_timer()
            self.asv.stop_movement()
            if hasattr(self.tracking_controller, 'reset'):
                self.tracking_controller.reset()
            print("[MissionEngine] 🔄 MISSION RESET.")
            self._broadcast_status()

    @property
    def status(self) -> str:
        return self._status

    @property
    def gate_lock_state(self) -> str:
        """Expose gate state machine state untuk OSD di tracker."""
        return self._gate_lock_state

    @property
    def current_step_id(self) -> int:
        with self._lock:
            if self._steps and self._current_step_idx < len(self._steps):
                return self._steps[self._current_step_idx].get("id", self._current_step_idx + 1)
            return 0

    def get_status_dict(self) -> Dict[str, Any]:
        with self._lock:
            current_step_info = {}
            if self._steps and self._current_step_idx < len(self._steps):
                current_step_info = self._steps[self._current_step_idx]

            step_elapsed = 0.0
            if self._status == self.STATUS_RUNNING and self._step_start_time is not None:
                step_elapsed = round(time.time() - self._step_start_time, 1)
            elif self._status == self.STATUS_PAUSED:
                step_elapsed = round(self._paused_step_elapsed, 1)

            return {
                "status": self._status,
                "current_step_idx": self._current_step_idx,
                "current_step": current_step_info,
                "total_steps": len(self._steps),
                "elapsed_sec": self._elapsed_sec,
                "step_elapsed_sec": max(0.0, step_elapsed),
                "buoy_pass_count": self._buoy_pass_count,
                "gate_lock_state": self._gate_lock_state,
                "seq_current_pair": self._seq_pairs_cleared + 1,
                "seq_pairs_cleared": self._seq_pairs_cleared,
                "seq_gate_lock_state": self._seq_gate_lock_state,
            }

    # ------------------------------------------------------------------ #
    #  Frame Update Loop (dipanggil dari video_streamer callback ~30FPS)  #
    # ------------------------------------------------------------------ #

    def update_frame(self, frame, gate_x: Optional[float], detected_balls: Optional[Dict] = None):
        """
        Dipanggil oleh process_and_control() setiap frame.

        :param frame:          Frame kamera saat ini.
        :param gate_x:         Koordinat X midpoint gate dari tracker (fallback/visual).
        :param detected_balls: Dict {"red": [...], "green": [...]} dari tracker.process_frame().
                               Masing-masing berisi list (cx, cy, x1, y1, x2, y2).

        Return: (steer_norm, thr_norm, step_type_label)
        """
        with self._lock:
            if self._status != self.STATUS_RUNNING:
                return 0.0, 0.0, "IDLE"

            if self._current_step_idx >= len(self._steps):
                self._finish_mission()
                return 0.0, 0.0, "FINISH"

            step = self._steps[self._current_step_idx]
            step_type = step.get("type", "")

            # Inisialisasi timer & state saat baru masuk ke langkah ini
            if self._step_start_time is None:
                self._step_start_time = time.time() - self._paused_step_elapsed
                if step_type == self.STEP_TYPE_TRACKING_BUOY:
                    if hasattr(self.tracking_controller, 'reset'):
                        self.tracking_controller.reset()
                    self._reset_gate_state_machine()
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch Flight Controller mode -> MANUAL for TRACKING_BUOY...")
                        self.asv.set_mode("MANUAL")
                elif step_type == self.STEP_TYPE_TIMED_STEER:
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch mode → MANUAL untuk TIMED_STEER...")
                        self.asv.set_mode("MANUAL")
                elif step_type == self.STEP_TYPE_SEQUENTIAL_BUOY:
                    if hasattr(self.tracking_controller, 'reset'):
                        self.tracking_controller.reset()
                    self._reset_sequential_state()
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch mode → MANUAL untuk SEQUENTIAL_BUOY...")
                        self.asv.set_mode("MANUAL")
                elif step_type in (self.STEP_TYPE_HOLD, self.STEP_TYPE_TAKE_IMAGE):
                    # Pastikan mode GUIDED agar stop_movement() (send_velocity 0) efektif
                    if self.asv and self.asv.is_connected():
                        telemetry = self.asv.get_telemetry()
                        if telemetry.mode != "GUIDED":
                            print(f"[MissionEngine] 🔄 Switch mode → GUIDED untuk {step_type}...")
                            self.asv.set_mode("GUIDED")
                    self.asv.stop_movement()
                elif step_type in (self.STEP_TYPE_CUSTOM_FORWARD, self.STEP_TYPE_PRECISION_TURN):
                    # Switch ke GUIDED dan lepaskan RC override dari step MANUAL sebelumnya
                    if self.asv and self.asv.is_connected():
                        if self.asv.get_telemetry().mode != "GUIDED":
                            print(f"[MissionEngine] 🔄 Switch mode → GUIDED untuk {step_type}...")
                            self.asv.set_mode("GUIDED")
                        self.asv.release_rc()

            # ---- TRACKING_BUOY ----
            if step_type == self.STEP_TYPE_TRACKING_BUOY:
                return self._handle_tracking(step, gate_x, detected_balls or {"red": [], "green": []})

            # ---- GOTO_GPS ----
            elif step_type == self.STEP_TYPE_GOTO_GPS:
                return self._handle_goto_gps(step, frame, gate_x, detected_balls)

            # ---- TAKE_IMAGE ----
            elif step_type == self.STEP_TYPE_TAKE_IMAGE:
                return self._handle_take_image(step, frame, gate_x, detected_balls)

            # ---- HOLD ----
            elif step_type == self.STEP_TYPE_HOLD:
                return self._handle_hold(step, frame, gate_x, detected_balls)

            # ---- START (warmup sebentar) ----
            elif step_type == self.STEP_TYPE_START:
                warmup_sec = float(step.get("duration_sec", 2.0))
                if time.time() - self._step_start_time >= warmup_sec:
                    self._advance_step()
                    return self.update_frame(frame, gate_x, detected_balls)
                return 0.0, 0.0, "START"

            # ---- CUSTOM_FORWARD ----
            elif step_type == self.STEP_TYPE_CUSTOM_FORWARD:
                return self._handle_custom_forward(step)

            # ---- PRECISION_TURN ----
            elif step_type == self.STEP_TYPE_PRECISION_TURN:
                return self._handle_precision_turn(step)

            # ---- TIMED_STEER ----
            elif step_type == self.STEP_TYPE_TIMED_STEER:
                return self._handle_timed_steer(step)

            # ---- SEQUENTIAL_BUOY ----
            elif step_type == self.STEP_TYPE_SEQUENTIAL_BUOY:
                return self._handle_sequential_buoy(step, gate_x, detected_balls or {"red": [], "green": []})

            # ---- FINISH ----
            elif step_type == self.STEP_TYPE_FINISH:
                self._finish_mission()
                return 0.0, 0.0, "FINISH"

            else:
                # Unknown step — skip
                self._advance_step()
                return self.update_frame(frame, gate_x, detected_balls)

    # ------------------------------------------------------------------ #
    #  Step Handlers                                                      #
    # ------------------------------------------------------------------ #

    def _handle_tracking(self, step, gate_x: Optional[float], detected_balls: Dict):
        """
        Handle TRACKING_BUOY step menggunakan Gate State Machine.

        State Machine:
          SEARCHING    → Mencari pasangan bola. Gunakan gate_x fallback dari tracker.
          LOCKED       → Pasangan bola dikunci. PID ke midpoint locked pair.
          TRANSITIONING → Satu bola hilang. Manuver condong, DILARANG pair ulang.
          CLEARED      → Kedua bola hilang. Gate terlewati, reset ke SEARCHING.
        """
        target_pass_count = int(step.get("pass_count", 0))
        duration = float(step.get("duration_sec", 0.0))

        # --- Cek kondisi selesai berdasarkan pass_count ---
        if target_pass_count > 0 and self._buoy_pass_count >= target_pass_count:
            print(f"[MissionEngine] ✅ TRACKING_BUOY selesai! Pass count: {self._buoy_pass_count}/{target_pass_count}")
            self._reset_gate_state_machine()
            self._advance_step()
            return 0.0, 0.0, "TRACKING_BUOY"

        # --- Cek kondisi selesai berdasarkan duration ---
        if target_pass_count == 0 and duration > 0 and self._step_start_time and (time.time() - self._step_start_time >= duration):
            print(f"[MissionEngine] ✅ TRACKING_BUOY selesai! Durasi {duration}s terpenuhi.")
            self._reset_gate_state_machine()
            self._advance_step()
            return 0.0, 0.0, "TRACKING_BUOY"

        # Pastikan FC selalu berada di mode MANUAL saat menjalankan TRACKING_BUOY
        if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
            print("[MissionEngine] 🔄 Automatic mode switch to MANUAL for TRACKING_BUOY...")
            self.asv.set_mode("MANUAL")

        red_visible   = len(detected_balls.get("red", [])) > 0
        green_visible = len(detected_balls.get("green", [])) > 0
        throttle      = self.speed_scheduler.max_base_throttle

        pass_label = f"{self._buoy_pass_count}/{target_pass_count}" if target_pass_count > 0 else str(self._buoy_pass_count)

        # ══════════════════════════════════════════════════════
        #  GATE STATE MACHINE
        # ══════════════════════════════════════════════════════

        if self._gate_lock_state == self.GATE_SEARCHING:
            # ── SEARCHING ──────────────────────────────────────
            if red_visible and green_visible:
                # Kedua bola terlihat → LOCK pasangan
                closest_red   = detected_balls["red"][0]    # sorted foreground-first
                closest_green = detected_balls["green"][0]
                self._locked_red_pos   = (closest_red[0],   closest_red[1])
                self._locked_green_pos = (closest_green[0], closest_green[1])
                self._gate_lock_state  = self.GATE_LOCKED
                self._gate_state_entered_at = time.time()
                print(f"[GATE] SEARCHING → LOCKED "
                      f"(red=({self._locked_red_pos}), green=({self._locked_green_pos}))")

                # Hitung steer ke midpoint locked pair
                locked_midpoint_x = (self._locked_red_pos[0] + self._locked_green_pos[0]) // 2
                steer = self.tracking_controller.compute_normalized_steering(locked_midpoint_x)
                label = f"GATE:LOCKED | TRACKING_BUOY ({pass_label} pass)"
                return steer, throttle, label

            else:
                # Belum ada pasangan → gunakan gate_x fallback dari tracker
                if gate_x is not None:
                    steer = self.tracking_controller.compute_normalized_steering(gate_x)
                    label = f"GATE:SEARCHING | TRACKING_BUOY ({pass_label} pass)"
                    return steer, throttle, label
                else:
                    # Tidak ada target sama sekali → tetap maju lurus pelan agar tidak stuck diam
                    # Kapal terus bergerak maju sehingga buoy masuk frame kembali
                    label = f"GATE:SEARCHING (no target) | TRACKING_BUOY ({pass_label} pass)"
                    return 0.0, throttle, label

        elif self._gate_lock_state == self.GATE_LOCKED:
            # ── LOCKED ────────────────────────────────────────
            # Pastikan bola merah/hijau yang terdeteksi masih "bola yang sama"
            nearest_red = self._find_nearest_ball(detected_balls.get("red", []), self._locked_red_pos)
            nearest_green = self._find_nearest_ball(detected_balls.get("green", []), self._locked_green_pos)
            
            red_visible_locked = nearest_red is not None
            green_visible_locked = nearest_green is not None

            # ── Timeout guard: jika terlalu lama LOCKED tanpa bola hilang, kembali ke SEARCHING
            # Ini handle kasus kapal stuck menghadap gate tapi tidak bergerak maju.
            now = time.time()
            locked_duration = now - self._gate_state_entered_at
            if locked_duration > self.GATE_LOCKED_TIMEOUT_SEC and red_visible_locked and green_visible_locked:
                print(f"[GATE] LOCKED TIMEOUT ({locked_duration:.1f}s) → SEARCHING (reset untuk coba lagi)")
                self._reset_gate_state_machine()
                label = f"GATE:SEARCHING (timeout) | TRACKING_BUOY ({pass_label} pass)"
                return 0.0, throttle, label

            if red_visible_locked and green_visible_locked:
                # Kedua bola masih terlihat → update posisi locked pair (supaya smooth tracking)
                self._locked_red_pos   = (nearest_red[0],   nearest_red[1])
                self._locked_green_pos = (nearest_green[0], nearest_green[1])

                locked_midpoint_x = (self._locked_red_pos[0] + self._locked_green_pos[0]) // 2
                steer = self.tracking_controller.compute_normalized_steering(locked_midpoint_x)
                label = f"GATE:LOCKED | TRACKING_BUOY ({pass_label} pass)"
                return steer, throttle, label

            elif not red_visible_locked and green_visible_locked:
                # ★ Bola MERAH (kiri) hilang duluan → condong ke KIRI
                self._missing_side     = "left"
                self._gate_lock_state  = self.GATE_TRANSITIONING
                self._gate_state_entered_at = time.time()
                # Update posisi terakhir bola hijau yang terlihat
                self._locked_green_pos = (nearest_green[0], nearest_green[1])
                # Hitung steer adaptif: arahkan kapal ke bola hijau yang tersisa
                self._transition_steer = self.tracking_controller.compute_normalized_steering(
                    self._locked_green_pos[0]
                )
                # Override lean: paksa condong ke KIRI terlepas dari output PID
                # agar kapal mengarah ke sisi gate yang terbuka (merah hilang = arah kiri)
                lean = -abs(self.TRANSITION_LEAN_MAGNITUDE)
                self._transition_steer = min(self._transition_steer, lean)
                print(f"[GATE] LOCKED → TRANSITIONING (missing=LEFT/red, lean={self._transition_steer:+.2f})")
                label = f"GATE:TRANSITIONING(←) | TRACKING_BUOY ({pass_label} pass)"
                return self._transition_steer, throttle, label

            elif red_visible_locked and not green_visible_locked:
                # ★ Bola HIJAU (kanan) hilang duluan → condong ke KANAN
                self._missing_side     = "right"
                self._gate_lock_state  = self.GATE_TRANSITIONING
                self._gate_state_entered_at = time.time()
                # Update posisi terakhir bola merah yang terlihat
                self._locked_red_pos   = (nearest_red[0], nearest_red[1])
                # Hitung steer adaptif: arahkan kapal ke bola merah yang tersisa
                self._transition_steer = self.tracking_controller.compute_normalized_steering(
                    self._locked_red_pos[0]
                )
                # Override lean: paksa condong ke KANAN
                lean = +abs(self.TRANSITION_LEAN_MAGNITUDE)
                self._transition_steer = max(self._transition_steer, lean)
                print(f"[GATE] LOCKED → TRANSITIONING (missing=RIGHT/green, lean={self._transition_steer:+.2f})")
                label = f"GATE:TRANSITIONING(→) | TRACKING_BUOY ({pass_label} pass)"
                return self._transition_steer, throttle, label

            else:
                # Kedua bola hilang sekaligus dari LOCKED → langsung CLEARED
                self._gate_lock_state = self.GATE_CLEARED
                print("[GATE] LOCKED → CLEARED (kedua bola hilang bersamaan)")
                return self._handle_gate_cleared(pass_label, step)

        elif self._gate_lock_state == self.GATE_TRANSITIONING:
            # ── TRANSITIONING ─────────────────────────────────
            # Periksa apakah bola yang TERSISA (bukan yang hilang) masih terlihat.
            # DILARANG KERAS memperhitungkan bola dari gerbang berikutnya.
            remaining_visible = False
            
            if self._missing_side == "left":
                # Bola merah sudah hilang, tinggal tunggu bola hijau juga hilang.
                nearest_green = self._find_nearest_ball(detected_balls.get("green", []), self._locked_green_pos)
                if nearest_green:
                    remaining_visible = True
                    self._locked_green_pos = (nearest_green[0], nearest_green[1])
                    # Update steer adaptif: terus arahkan ke bola hijau yang tersisa
                    # Kombinasi: min(steer_adaptif, -lean_min) agar selalu condong ke kiri
                    adaptive_steer = self.tracking_controller.compute_normalized_steering(
                        self._locked_green_pos[0]
                    )
                    self._transition_steer = min(adaptive_steer, -abs(self.TRANSITION_LEAN_MAGNITUDE))
            elif self._missing_side == "right":
                # Bola hijau sudah hilang, tinggal tunggu bola merah juga hilang.
                nearest_red = self._find_nearest_ball(detected_balls.get("red", []), self._locked_red_pos)
                if nearest_red:
                    remaining_visible = True
                    self._locked_red_pos = (nearest_red[0], nearest_red[1])
                    # Update steer adaptif: terus arahkan ke bola merah yang tersisa
                    # Kombinasi: max(steer_adaptif, +lean_min) agar selalu condong ke kanan
                    adaptive_steer = self.tracking_controller.compute_normalized_steering(
                        self._locked_red_pos[0]
                    )
                    self._transition_steer = max(adaptive_steer, +abs(self.TRANSITION_LEAN_MAGNITUDE))

            # ── Timeout guard TRANSITIONING ───────────────────
            # Jika terlalu lama di TRANSITIONING (bola tersisa terus terlihat), paksa CLEARED.
            # Ini handle kasus bola dari gerbang BERIKUTNYA masuk frame sebelum bola ini hilang.
            transitioning_duration = time.time() - self._gate_state_entered_at
            if transitioning_duration > self.GATE_TRANSITIONING_TIMEOUT_SEC:
                print(f"[GATE] TRANSITIONING TIMEOUT ({transitioning_duration:.1f}s) → CLEARED (paksa)")
                self._gate_lock_state = self.GATE_CLEARED
                return self._handle_gate_cleared(pass_label, step)

            if remaining_visible:
                # Bola tersisa masih ada di frame → pertahankan manuver condong adaptif
                lean_dir = "←" if self._missing_side == "left" else "→"
                label = f"GATE:TRANSITIONING({lean_dir}) steer={self._transition_steer:+.2f} | TRACKING_BUOY ({pass_label} pass)"
                return self._transition_steer, throttle, label
            else:
                # Bola terakhir juga hilang → gate CLEARED!
                self._gate_lock_state = self.GATE_CLEARED
                print("[GATE] TRANSITIONING → CLEARED (bola terakhir hilang)")
                return self._handle_gate_cleared(pass_label, step)

        # Fallback safety
        return 0.0, 0.0, f"GATE:UNKNOWN | TRACKING_BUOY ({pass_label} pass)"

    def _handle_gate_cleared(self, pass_label: str, step: Dict) -> Tuple[float, float, str]:
        """
        Dipanggil saat gate dinyatakan CLEARED.
        Increment pass count, reset state machine, dan kembali ke SEARCHING.
        """
        self._buoy_pass_count += 1
        target_pass_count = int(step.get("pass_count", 0))
        new_pass_label = f"{self._buoy_pass_count}/{target_pass_count}" if target_pass_count > 0 else str(self._buoy_pass_count)

        print(f"[GATE] 🏁 Gate CLEARED! Pass count: {self._buoy_pass_count}")
        self._broadcast_status()
        self._reset_gate_state_machine()   # kembali ke SEARCHING untuk gerbang berikutnya
        print(f"[GATE] CLEARED → SEARCHING (siap mengincar gerbang berikutnya)")

        label = f"GATE:CLEARED ✅ | TRACKING_BUOY ({new_pass_label} pass)"
        # Hentikan throttle sejenak agar tidak menabrak gate berikutnya
        return 0.0, 0.0, label

    def _handle_goto_gps(self, step, frame, gate_x, detected_balls=None):
        """Handle GOTO_GPS step."""
        target_lat = float(step.get("lat", 0.0))
        target_lon = float(step.get("lon", 0.0))

        now = time.time()
        telemetry = self.asv.get_telemetry()

        # Throttle pengiriman command goto_target agar tidak flooding MAVLink (setiap 1.5 detik)
        if telemetry.is_armed and (now - self._last_goto_time >= 1.5):
            self.asv.goto(target_lat, target_lon)
            self._last_goto_time = now

        # Cek apakah sudah sampai (radius acceptance) jika ada sinyal GPS valid
        if telemetry.lat != 0 and telemetry.lon != 0:
            dist = self._haversine(telemetry.lat, telemetry.lon, target_lat, target_lon)
            if dist <= self.ARRIVAL_RADIUS_M:
                print(f"[MissionEngine] ✅ GOTO step selesai! Tiba di {step.get('name','?')}")
                self._advance_step()
                return self.update_frame(frame, gate_x, detected_balls)

        return 0.0, 0.0, "GOTO_GPS"

    def _handle_take_image(self, step, frame, gate_x, detected_balls=None):
        """Handle TAKE_IMAGE step."""
        duration = float(step.get("duration_sec", 3.0))
        elapsed = time.time() - self._step_start_time

        if elapsed >= duration:
            print(f"[MissionEngine] ✅ TAKE_IMAGE selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x, detected_balls)

        return 0.0, 0.0, "TAKE_IMAGE"

    def _handle_hold(self, step, frame, gate_x, detected_balls=None):
        """Handle HOLD step."""
        duration = float(step.get("duration_sec", 5.0))
        elapsed = time.time() - self._step_start_time

        if elapsed >= duration:
            print(f"[MissionEngine] ✅ HOLD selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x, detected_balls)

        # Kirim perintah stop berulang setiap frame agar motor betul-betul berhenti
        # (MAVLink GUIDED velocity = 0, tidak membutuhkan RC override)
        if self.asv and self.asv.is_connected():
            self.asv.stop_movement(silent=True)

        remaining = max(0.0, duration - elapsed)
        return 0.0, 0.0, f"HOLD | rem={remaining:.1f}s"

    # ------------------------------------------------------------------ #
    #  Dynamic Movement Handlers                                         #
    # ------------------------------------------------------------------ #

    def _handle_custom_forward(self, step: Dict) -> Tuple[float, float, str]:
        """
        Handle CUSTOM_FORWARD step.

        Kapal bergerak maju dengan kecepatan `speed_mps` (m/s) selama `duration_sec` detik.
        Selama bergerak, `heading_offset_deg` diterapkan sebagai yaw rate konstan (°/s):
          - heading_offset_deg = 0  → maju lurus
          - heading_offset_deg = +5 → condong kanan 5°/s (lintasan serong kanan)
          - heading_offset_deg = -5 → condong kiri 5°/s (lintasan serong kiri)

        Gerak dikirim via NavigationControl.send_velocity() → MAVLink SET_POSITION_TARGET_LOCAL_NED
        dalam mode GUIDED. TIDAK ADA direct PWM/servo override.

        Variabel step yang digunakan:
          step['speed_mps']          (float) — Kecepatan maju dalam m/s. Default: 0.5
          step['heading_offset_deg'] (float) — Yaw rate konstan (°/s). Default: 0.0
          step['duration_sec']       (float) — Batas waktu dalam detik. Default: 5.0
        """
        speed_mps          = float(step.get("speed_mps", 0.5))
        heading_offset_deg = float(step.get("heading_offset_deg", 0.0))
        duration_sec       = float(step.get("duration_sec", 5.0))

        elapsed = time.time() - self._step_start_time

        # Cek kondisi selesai berdasarkan timer
        if elapsed >= duration_sec:
            print(f"[MissionEngine] ✅ CUSTOM_FORWARD selesai! Durasi {duration_sec:.1f}s terpenuhi.")
            self.asv.stop_movement()
            self._advance_step()
            return 0.0, 0.0, "CUSTOM_FORWARD"

        # Kirim perintah gerak: maju dengan yaw rate = heading_offset_deg
        # Gerakan dikontrol oleh send_velocity() di mode GUIDED — bukan RC override.
        # Mode switch sudah dilakukan di init block (step_start_time is None).
        self.asv.nav.send_velocity(
            forward_speed=speed_mps,
            turn_rate_deg=heading_offset_deg
        )

        remaining = max(0.0, duration_sec - elapsed)
        offset_label = f"+{heading_offset_deg:.1f}°" if heading_offset_deg >= 0 else f"{heading_offset_deg:.1f}°"
        label = (f"CUSTOM_FORWARD | spd={speed_mps:.1f}m/s offset={offset_label} "
                 f"rem={remaining:.1f}s")
        # Return (0.0, 0.0) — movement via send_velocity(), NOT RC override.
        # main.py hanya kirim send_manual_rc_drive saat thr_norm > 0 atau mode MANUAL.
        return 0.0, 0.0, label

    def _handle_precision_turn(self, step: Dict) -> Tuple[float, float, str]:
        """
        Handle PRECISION_TURN step.

        Kapal berputar di tempat hingga mencapai sudut `turn_angle_deg` dari heading awal.
        Menggunakan feedback `telemetry.heading` (0-360°) dari ArduPilot kompas/GPS untuk
        mengukur kemajuan belok secara akurat.

        Algoritma:
          1. Frame pertama: rekam `_turn_initial_heading` dari telemetry.heading
             Hitung `_turn_target_heading` = (initial + turn_angle_deg) % 360
          2. Setiap frame: hitung `heading_error` (selisih angular, range -180..+180)
             Positive error → perlu belok kanan lebih; negative error → perlu belok kiri.
          3. Jika abs(heading_error) <= TURN_ARRIVAL_THRESHOLD_DEG (3°): selesai → stop + advance.
          4. Jika belum: kirim yaw rate = sign(heading_error) × turn_rate_dps, forward_speed = 0.

        Variabel step yang digunakan:
          step['turn_angle_deg'] (float) — Sudut total belok. +90 = kanan 90°, -90 = kiri 90°. Default: 90
          step['turn_rate_dps']  (float) — Kecepatan rotasi dalam °/s. Default: 20

        Variabel state engine:
          self._turn_initial_heading (Optional[float]) — Heading awal saat step dimulai (0-360°).
          self._turn_target_heading  (Optional[float]) — Heading target setelah belok (0-360°).
        """
        turn_angle_deg = float(step.get("turn_angle_deg", 90.0))
        turn_rate_dps  = float(step.get("turn_rate_dps", 20.0))

        # Ambil telemetri untuk mendapatkan heading saat ini
        telemetry = self.asv.get_telemetry() if self.asv else None
        current_heading = getattr(telemetry, "heading", None) if telemetry else None

        # --- Inisialisasi target heading di frame pertama step ini ---
        if self._turn_initial_heading is None:
            if current_heading is None:
                # Belum ada data heading (GPS/kompas belum siap) — tunggu
                print("[MissionEngine] ⏳ PRECISION_TURN: Menunggu data heading dari telemetri...")
                return 0.0, 0.0, "PRECISION_TURN: WAITING_HEADING"

            self._turn_initial_heading = float(current_heading)
            # Target heading = initial + angle, dinormalisasi ke 0-360°
            self._turn_target_heading  = (self._turn_initial_heading + turn_angle_deg) % 360.0
            turn_dir_label = "CW (kanan)" if turn_angle_deg >= 0 else "CCW (kiri)"
            print(f"[MissionEngine] 🧭 PRECISION_TURN dimulai: "
                  f"initial={self._turn_initial_heading:.1f}° "
                  f"target={self._turn_target_heading:.1f}° "
                  f"({turn_dir_label}, {abs(turn_angle_deg):.1f}°)")

        # --- Hitung heading error (range -180..+180) ---
        if current_heading is None:
            # Kehilangan sinyal heading sementara — pertahankan yaw rate terakhir
            active_dir = math.copysign(turn_rate_dps, turn_angle_deg)
            self.asv.nav.send_velocity(forward_speed=0.0, turn_rate_deg=active_dir)
            return 0.0, 0.0, "PRECISION_TURN: HEADING_LOST"

        heading_error = self._angular_diff(float(current_heading), self._turn_target_heading)

        # --- Cek apakah sudah sampai target ---
        if abs(heading_error) <= self.TURN_ARRIVAL_THRESHOLD_DEG:
            print(f"[MissionEngine] ✅ PRECISION_TURN selesai! "
                  f"Heading={current_heading:.1f}° (target={self._turn_target_heading:.1f}°, "
                  f"error={heading_error:+.1f}°)")
            self.asv.stop_movement()
            self._advance_step()
            return 0.0, 0.0, "PRECISION_TURN"

        # --- Belum sampai: kirim yaw rate ke arah yang benar ---
        # sign(heading_error): positif = perlu belok kanan, negatif = perlu belok kiri
        yaw_direction = math.copysign(1.0, heading_error)
        self.asv.nav.send_velocity(
            forward_speed=0.0,
            turn_rate_deg=yaw_direction * turn_rate_dps
        )

        label = (f"PRECISION_TURN | hdg={current_heading:.1f}° "
                 f"target={self._turn_target_heading:.1f}° err={heading_error:+.1f}°")
        return 0.0, 0.0, label

    def _handle_timed_steer(self, step: Dict) -> Tuple[float, float, str]:
        """
        Handle TIMED_STEER step.

        Kapal bergerak dengan steer dan throttle yang ditentukan selama `duration_sec` detik
        menggunakan RC override pada mode MANUAL. Tidak ada feedback GPS/kompas — murni timer.

        Cocok untuk: belok kiri/kanan di tempat, maju sambil belok, atau gerak lurus singkat
        sebelum/sesudah TRACKING_BUOY tanpa perlu switch ke mode GUIDED.

        Variabel step yang digunakan:
          step['steer']        (float) — Steering normalized: -1.0 (kiri penuh) .. +1.0 (kanan penuh). Default: 0.0
          step['throttle']     (float) — Throttle ratio: 0.0 (berhenti) .. 1.0 (full maju). Default: 0.3
          step['duration_sec'] (float) — Durasi maneuver dalam detik. Default: 3.0
        """
        steer       = max(-1.0, min(1.0, float(step.get("steer", 0.0))))
        throttle    = max(0.0, min(1.0, float(step.get("throttle", 0.3))))
        duration_sec = float(step.get("duration_sec", 3.0))

        elapsed = time.time() - self._step_start_time

        if elapsed >= duration_sec:
            print(f"[MissionEngine] ✅ TIMED_STEER selesai! Durasi {duration_sec:.1f}s terpenuhi.")
            self._advance_step()
            return 0.0, 0.0, "TIMED_STEER"

        remaining = max(0.0, duration_sec - elapsed)
        dir_label = "←" if steer < -0.05 else ("→" if steer > 0.05 else "↑")
        label = (f"TIMED_STEER {dir_label} | steer={steer:+.2f} thr={throttle:.2f} "
                 f"rem={remaining:.1f}s")
        return steer, throttle, label

    # ------------------------------------------------------------------ #
    #  Sequential Buoy Tracking Handlers                                 #
    # ------------------------------------------------------------------ #

    def _handle_sequential_buoy(self, step, gate_x: Optional[float], detected_balls: Dict):
        """
        Handle SEQUENTIAL_BUOY step.

        Menavigasi kapal melewati `total_pairs` pasang buoy (hijau + merah) secara berurutan.
        Pasangan diurutkan berdasarkan jarak terdekat ke kamera (bounding box terbesar = terdekat),
        sehingga Pasangan 1 = pasang buoy paling dekat, Pasangan 2 = berikutnya, dst.

        State Machine Dua Level:
          Level 1 — Pair Sequencer : menentukan pasangan mana yang sedang diproses.
          Level 2 — Gate FSM       : SEARCHING → LOCKED → TRANSITIONING → CLEARED → (pair selesai)

        Aturan Sorting (saat SEARCHING):
          _sort_buoy_pairs() mengurutkan pasangan berdasarkan rata-rata area bounding box
          (area terbesar = paling dekat ke kamera). Hanya dipanggil saat state SEARCHING
          untuk menentukan pasangan yang akan dikunci.

        Aturan Gate FSM (saat LOCKED / TRANSITIONING):
          Setelah pasangan dikunci, _sort_buoy_pairs() TIDAK dipanggil lagi.
          Bola yang tersisa dilacak via _find_nearest_ball() terhadap posisi kunci terakhir,
          identik dengan logika TRACKING_BUOY. Ini mencegah bola pasangan berikutnya
          yang masuk frame mengganggu gate FSM yang sedang berjalan.

        Aturan transisi lean:
          - Bola kiri (merah) hilang duluan → kapal condong ke KIRI  (steer negatif)
          - Bola kanan (hijau) hilang duluan → kapal condong ke KANAN (steer positif)
          - Kedua bola hilang                → pasangan CLEARED, lanjut ke pasangan berikutnya

        Format step:
          { "type": "SEQUENTIAL_BUOY", "total_pairs": 3 }
        """
        total_pairs = int(step.get("total_pairs", 3))
        throttle    = self.speed_scheduler.max_base_throttle
        cleared     = self._seq_pairs_cleared
        pair_num    = cleared + 1   # Display: pasangan yang sedang diincar (1-indexed)

        # ── Cek kondisi step selesai ─────────────────────────────────────
        if cleared >= total_pairs:
            print(f"[SEQ_BUOY] ✅ Semua {total_pairs} pasangan berhasil dilewati!")
            self._reset_sequential_state()
            self._advance_step()
            return 0.0, 0.0, "SEQUENTIAL_BUOY"

        # ── Pastikan mode MANUAL ─────────────────────────────────────────
        if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
            print("[MissionEngine] 🔄 Automatic mode switch to MANUAL for SEQUENTIAL_BUOY...")
            self.asv.set_mode("MANUAL")

        pair_label = f"{pair_num}/{total_pairs}"

        # ══════════════════════════════════════════════════════════════════
        #  GATE STATE MACHINE (Level 2) — menggunakan _seq_* state vars
        #  DILARANG menggunakan _gate_* vars milik TRACKING_BUOY.
        # ══════════════════════════════════════════════════════════════════

        if self._seq_gate_lock_state == self.GATE_SEARCHING:
            # ── SEARCHING ──────────────────────────────────────────────
            # Sort HANYA di state SEARCHING untuk menentukan pasangan target.
            # Pasangan[0] = pasangan terdekat (area rata-rata bounding box terbesar).
            pairs      = self._sort_buoy_pairs(detected_balls)
            target_pair = pairs[0] if pairs else None

            red_ball   = target_pair[0] if target_pair else None
            green_ball = target_pair[1] if target_pair else None
            red_visible   = red_ball is not None
            green_visible = green_ball is not None

            if red_visible and green_visible:
                # Kedua bola terlihat → LOCK pasangan terdekat
                self._seq_locked_red_pos   = (red_ball[0],   red_ball[1])
                self._seq_locked_green_pos = (green_ball[0], green_ball[1])
                self._seq_gate_lock_state  = self.GATE_LOCKED
                self._seq_gate_state_entered_at = time.time()
                print(f"[SEQ_GATE] SEARCHING → LOCKED "
                      f"(pair {pair_label}, red={self._seq_locked_red_pos}, "
                      f"green={self._seq_locked_green_pos})")
                locked_mid_x = (self._seq_locked_red_pos[0] + self._seq_locked_green_pos[0]) // 2
                steer = self.tracking_controller.compute_normalized_steering(locked_mid_x)
                label = f"SEQ_GATE:LOCKED | SEQUENTIAL_BUOY (pair {pair_label})"
                return steer, throttle, label
            else:
                # Belum ada pasangan lengkap → gunakan gate_x fallback dari tracker
                if gate_x is not None:
                    steer = self.tracking_controller.compute_normalized_steering(gate_x)
                    label = f"SEQ_GATE:SEARCHING | SEQUENTIAL_BUOY (pair {pair_label})"
                    return steer, throttle, label
                else:
                    # Tidak ada target sama sekali → tetap maju lurus agar buoy masuk frame
                    label = f"SEQ_GATE:SEARCHING (no target) | SEQUENTIAL_BUOY (pair {pair_label})"
                    return 0.0, throttle, label

        elif self._seq_gate_lock_state == self.GATE_LOCKED:
            # ── LOCKED ─────────────────────────────────────────────────
            # Jangan panggil _sort_buoy_pairs() di sini.
            # Gunakan _find_nearest_ball() terhadap posisi kunci agar bola dari
            # pasangan berikutnya yang masuk frame tidak mengganggu gate FSM.
            nearest_red   = self._find_nearest_ball(
                detected_balls.get("red",   []), self._seq_locked_red_pos)
            nearest_green = self._find_nearest_ball(
                detected_balls.get("green", []), self._seq_locked_green_pos)

            red_visible_locked   = nearest_red   is not None
            green_visible_locked = nearest_green is not None

            # ── Timeout guard: terlalu lama LOCKED tanpa bola hilang → kembali SEARCHING
            now = time.time()
            locked_duration = now - self._seq_gate_state_entered_at
            if locked_duration > self.GATE_LOCKED_TIMEOUT_SEC and red_visible_locked and green_visible_locked:
                print(f"[SEQ_GATE] LOCKED TIMEOUT ({locked_duration:.1f}s) → SEARCHING (pair {pair_label})")
                self._reset_sequential_gate_fsm()
                label = f"SEQ_GATE:SEARCHING (timeout) | SEQUENTIAL_BUOY (pair {pair_label})"
                return 0.0, throttle, label

            if red_visible_locked and green_visible_locked:
                # Kedua bola masih terlihat → update posisi locked pair & PID ke midpoint
                self._seq_locked_red_pos   = (nearest_red[0],   nearest_red[1])
                self._seq_locked_green_pos = (nearest_green[0], nearest_green[1])
                locked_mid_x = (self._seq_locked_red_pos[0] + self._seq_locked_green_pos[0]) // 2
                steer = self.tracking_controller.compute_normalized_steering(locked_mid_x)
                label = f"SEQ_GATE:LOCKED | SEQUENTIAL_BUOY (pair {pair_label})"
                return steer, throttle, label

            elif not red_visible_locked and green_visible_locked:
                # ★ Bola MERAH (kiri) hilang duluan → condong ke KIRI
                self._seq_missing_side      = "left"
                self._seq_gate_lock_state   = self.GATE_TRANSITIONING
                self._seq_gate_state_entered_at = time.time()
                self._seq_locked_green_pos  = (nearest_green[0], nearest_green[1])
                # Steer adaptif ke bola hijau tersisa, dipaksa condong minimum ke kiri
                adaptive_steer = self.tracking_controller.compute_normalized_steering(
                    self._seq_locked_green_pos[0])
                lean = -abs(self.TRANSITION_LEAN_MAGNITUDE)
                self._seq_transition_steer  = min(adaptive_steer, lean)
                print(f"[SEQ_GATE] LOCKED → TRANSITIONING "
                      f"(pair {pair_label}, missing=LEFT/red, lean={self._seq_transition_steer:+.2f})")
                label = f"SEQ_GATE:TRANSITIONING(←) | SEQUENTIAL_BUOY (pair {pair_label})"
                return self._seq_transition_steer, throttle, label

            elif red_visible_locked and not green_visible_locked:
                # ★ Bola HIJAU (kanan) hilang duluan → condong ke KANAN
                self._seq_missing_side      = "right"
                self._seq_gate_lock_state   = self.GATE_TRANSITIONING
                self._seq_gate_state_entered_at = time.time()
                self._seq_locked_red_pos    = (nearest_red[0], nearest_red[1])
                # Steer adaptif ke bola merah tersisa, dipaksa condong minimum ke kanan
                adaptive_steer = self.tracking_controller.compute_normalized_steering(
                    self._seq_locked_red_pos[0])
                lean = +abs(self.TRANSITION_LEAN_MAGNITUDE)
                self._seq_transition_steer  = max(adaptive_steer, lean)
                print(f"[SEQ_GATE] LOCKED → TRANSITIONING "
                      f"(pair {pair_label}, missing=RIGHT/green, lean={self._seq_transition_steer:+.2f})")
                label = f"SEQ_GATE:TRANSITIONING(→) | SEQUENTIAL_BUOY (pair {pair_label})"
                return self._seq_transition_steer, throttle, label

            else:
                # Kedua bola hilang sekaligus dari LOCKED → langsung CLEARED
                self._seq_gate_lock_state = self.GATE_CLEARED
                print(f"[SEQ_GATE] LOCKED → CLEARED (pair {pair_label}, kedua bola hilang bersamaan)")
                return self._handle_seq_gate_cleared(pair_num, total_pairs)

        elif self._seq_gate_lock_state == self.GATE_TRANSITIONING:
            # ── TRANSITIONING ──────────────────────────────────────────
            # Tunggu bola TERSISA (bukan yang hilang) juga hilang dari frame.
            # DILARANG KERAS memperhitungkan bola dari pasangan berikutnya.
            # Gunakan _find_nearest_ball() agar identitas bola tetap terjaga.
            remaining_visible = False

            if self._seq_missing_side == "left":
                # Bola merah sudah hilang → tunggu bola hijau juga hilang
                nearest_green = self._find_nearest_ball(
                    detected_balls.get("green", []), self._seq_locked_green_pos)
                if nearest_green:
                    remaining_visible = True
                    self._seq_locked_green_pos = (nearest_green[0], nearest_green[1])
                    # Update steer adaptif: terus arahkan ke bola hijau tersisa + pertahankan lean kiri
                    adaptive_steer = self.tracking_controller.compute_normalized_steering(
                        self._seq_locked_green_pos[0])
                    self._seq_transition_steer = min(adaptive_steer, -abs(self.TRANSITION_LEAN_MAGNITUDE))

            elif self._seq_missing_side == "right":
                # Bola hijau sudah hilang → tunggu bola merah juga hilang
                nearest_red = self._find_nearest_ball(
                    detected_balls.get("red", []), self._seq_locked_red_pos)
                if nearest_red:
                    remaining_visible = True
                    self._seq_locked_red_pos = (nearest_red[0], nearest_red[1])
                    # Update steer adaptif: terus arahkan ke bola merah tersisa + pertahankan lean kanan
                    adaptive_steer = self.tracking_controller.compute_normalized_steering(
                        self._seq_locked_red_pos[0])
                    self._seq_transition_steer = max(adaptive_steer, +abs(self.TRANSITION_LEAN_MAGNITUDE))

            # ── Timeout guard TRANSITIONING: paksa CLEARED jika terlalu lama ─
            transitioning_duration = time.time() - self._seq_gate_state_entered_at
            if transitioning_duration > self.GATE_TRANSITIONING_TIMEOUT_SEC:
                print(f"[SEQ_GATE] TRANSITIONING TIMEOUT ({transitioning_duration:.1f}s) "
                      f"→ CLEARED (pair {pair_label}, paksa)")
                self._seq_gate_lock_state = self.GATE_CLEARED
                return self._handle_seq_gate_cleared(pair_num, total_pairs)

            if remaining_visible:
                # Bola tersisa masih di frame → pertahankan manuver condong adaptif
                lean_dir = "←" if self._seq_missing_side == "left" else "→"
                label = (f"SEQ_GATE:TRANSITIONING({lean_dir}) "
                         f"steer={self._seq_transition_steer:+.2f} "
                         f"| SEQUENTIAL_BUOY (pair {pair_label})")
                return self._seq_transition_steer, throttle, label
            else:
                # Bola terakhir juga hilang → pasangan CLEARED!
                self._seq_gate_lock_state = self.GATE_CLEARED
                print(f"[SEQ_GATE] TRANSITIONING → CLEARED (pair {pair_label}, bola terakhir hilang)")
                return self._handle_seq_gate_cleared(pair_num, total_pairs)

        # Fallback safety
        return 0.0, 0.0, f"SEQ_GATE:UNKNOWN | SEQUENTIAL_BUOY (pair {pair_label})"

    def _handle_seq_gate_cleared(self, pair_num: int, total_pairs: int) -> Tuple[float, float, str]:
        """
        Dipanggil saat satu pasangan gate dinyatakan CLEARED.
        Increment cleared counter, reset gate FSM level-2, siap untuk pasangan berikutnya.
        """
        self._seq_pairs_cleared += 1
        new_cleared = self._seq_pairs_cleared

        print(f"[SEQ_GATE] 🏁 Pair {pair_num} CLEARED! ({new_cleared}/{total_pairs} selesai)")
        self._broadcast_status()
        self._reset_sequential_gate_fsm()  # Reset gate FSM, tapi PERTAHANKAN pair counter

        if new_cleared < total_pairs:
            next_pair = new_cleared + 1
            print(f"[SEQ_GATE] CLEARED → SEARCHING (siap mengincar pasangan {next_pair}/{total_pairs})")

        label = f"SEQ_GATE:CLEARED ✅ | SEQUENTIAL_BUOY (pair {pair_num}/{total_pairs})"
        # Berhenti sejenak agar tidak langsung menabrak pasangan berikutnya
        return 0.0, 0.0, label

    def _sort_buoy_pairs(self, detected_balls: Dict) -> List[Tuple]:
        """
        Mengurutkan buoy yang terdeteksi menjadi pasangan (merah, hijau) berdasarkan
        estimasi jarak terdekat dari kamera (area bounding box terbesar = paling dekat).

        Algoritma:
          1. Sort bola merah berdasarkan area bounding box (terbesar = terdekat duluan).
          2. Sort bola hijau berdasarkan area bounding box (terbesar = terdekat duluan).
          3. Greedy matching: untuk setiap bola merah (urut dari terdekat),
             temukan bola hijau yang belum dipakai dengan jarak piksel terdekat.
          4. Sort akhir pasangan berdasarkan rata-rata area (double-check),
             sehingga Pasangan 1 = terdekat ke kamera, Pasangan 2 = berikutnya, dst.

        BallTracker.process_frame() sudah mensort setiap class berdasarkan area
        (foreground-first), namun sort eksplisit di sini memastikan konsistensi
        meski tracker berubah di masa depan.

        Returns:
            List of (red_ball, green_ball) — max 3 pasangan, urut dari terdekat ke terjauh.
            Setiap elemen adalah tuple (cx, cy, x1, y1, x2, y2).
        """
        raw_red   = list(detected_balls.get("red",   []))
        raw_green = list(detected_balls.get("green", []))

        if not raw_red or not raw_green:
            return []

        # 1. Sort setiap class berdasarkan area bounding box (terbesar = paling dekat kamera)
        def _ball_area(ball: Tuple) -> float:
            return float((ball[4] - ball[2]) * (ball[5] - ball[3]))  # (x2-x1)*(y2-y1)

        red_list   = sorted(raw_red[:3],   key=_ball_area, reverse=True)  # max 3 merah
        green_list = sorted(raw_green[:3], key=_ball_area, reverse=True)  # max 3 hijau

        pairs: List[Tuple] = []
        used_green: set = set()

        # 2. Greedy matching: untuk setiap bola merah (urut terdekat → terjauh),
        #    cari bola hijau terdekat secara piksel yang belum dipakai.
        for red in red_list:
            rx, ry = red[0], red[1]
            best_green     = None
            best_dist      = float("inf")
            best_green_idx = -1

            for gi, grn in enumerate(green_list):
                if gi in used_green:
                    continue
                gx, gy = grn[0], grn[1]
                dist = math.hypot(rx - gx, ry - gy)
                if dist < best_dist:
                    best_dist      = dist
                    best_green     = grn
                    best_green_idx = gi

            if best_green is not None:
                used_green.add(best_green_idx)
                pairs.append((red, best_green))

            if len(pairs) >= 3:
                break

        # 3. Sort akhir pasangan berdasarkan rata-rata area (terbesar = terdekat = Pasangan 1)
        def _pair_avg_area(pair: Tuple) -> float:
            r, g = pair
            return (_ball_area(r) + _ball_area(g)) / 2.0

        pairs.sort(key=_pair_avg_area, reverse=True)
        return pairs

    def _reset_sequential_gate_fsm(self):
        """
        Reset HANYA gate FSM Sequential Buoy (Level 2) ke SEARCHING.
        TIDAK mereset pair counter (_seq_pairs_cleared).
        Gunakan saat satu pasangan selesai dan siap mengincar pasangan berikutnya.
        """
        self._seq_gate_lock_state       = self.GATE_SEARCHING
        self._seq_locked_red_pos        = None
        self._seq_locked_green_pos      = None
        self._seq_missing_side          = None
        self._seq_transition_steer      = 0.0
        self._seq_gate_state_entered_at = 0.0
        self._seq_gate_pause_start      = 0.0

    def _reset_sequential_state(self):
        """
        Reset SEMUA state Sequential Buoy termasuk pair counter.
        Gunakan saat mission dimulai, di-load, atau di-reset dari awal.
        """
        self._seq_pairs_cleared = 0
        self._reset_sequential_gate_fsm()

    @staticmethod
    def _angular_diff(current_deg: float, target_deg: float) -> float:
        """
        Hitung selisih angular antara dua heading (0-360°) dalam range -180..+180.

        Positif = target ada di kanan (perlu belok CW).
        Negatif = target ada di kiri (perlu belok CCW).

        Contoh:
          current=350°, target=10° → diff=+20° (belok kanan 20°)
          current=10°, target=350° → diff=-20° (belok kiri 20°)
        """
        diff = (target_deg - current_deg + 540.0) % 360.0 - 180.0
        return diff

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _reset_gate_state_machine(self):
        """Reset semua variabel Gate State Machine ke kondisi awal (SEARCHING)."""
        self._gate_lock_state      = self.GATE_SEARCHING
        self._locked_red_pos       = None
        self._locked_green_pos     = None
        self._missing_side         = None
        self._transition_steer     = 0.0
        self._gate_state_entered_at = 0.0
        self._gate_pause_start     = 0.0

    def _find_nearest_ball(self, balls: List[Tuple], locked_pos: Optional[Tuple[int, int]]) -> Optional[Tuple]:
        """
        Temukan bola dari list yang paling dekat dengan locked_pos
        dan masih dalam threshold GATE_IDENTITY_MAX_DIST_PX.

        Returns: tuple (cx, cy, x1, y1, x2, y2) atau None jika tidak ada yang memenuhi threshold.
        """
        if not balls or locked_pos is None:
            return None

        best = None
        best_dist = float("inf")
        lx, ly = locked_pos

        for ball in balls:
            cx, cy = ball[0], ball[1]
            dist = math.hypot(cx - lx, cy - ly)
            if dist < best_dist:
                best_dist = dist
                best = ball

        if best_dist <= self.GATE_IDENTITY_MAX_DIST_PX:
            return best
        return None  # Bola terlalu jauh → bola gerbang lain, abaikan

    def _advance_step(self):
        self._current_step_idx += 1
        self._step_start_time = None
        self._paused_step_elapsed = 0.0
        self._last_goto_time = 0.0
        self._reset_gate_state_machine()
        self._buoy_pass_count = 0  # Reset counter untuk step tracking berikutnya
        # Reset PRECISION_TURN state
        self._turn_initial_heading = None
        self._turn_target_heading  = None

        if self._current_step_idx < len(self._steps):
            next_step = self._steps[self._current_step_idx]
            print(f"[MissionEngine] ➡️ Step #{self._current_step_idx + 1}: {next_step.get('name', '?')} ({next_step.get('type', '?')})")
        self._broadcast_status()

    def _finish_mission(self):
        self._status = self.STATUS_FINISHED
        self._stop_elapsed_timer()
        self.asv.stop_movement()  # Hentikan gerak, JANGAN ubah mode
        print("[MissionEngine] 🎉 MISSION FINISHED SUCCESSFULLY!")
        self._broadcast_status()

    def _haversine(self, lat1, lon1, lat2, lon2) -> float:
        """Hitung jarak di permukaan bumi dalam meter."""
        R = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _broadcast_status(self):
        if self._status_callback:
            try:
                self._status_callback(self.get_status_dict())
            except Exception as e:
                print(f"[MissionEngine] Callback error: {e}")

    def _start_elapsed_timer(self):
        self._elapsed_running = True
        self._elapsed_thread = threading.Thread(target=self._elapsed_loop, daemon=True)
        self._elapsed_thread.start()

    def _stop_elapsed_timer(self):
        self._elapsed_running = False

    def _elapsed_loop(self):
        while self._elapsed_running:
            time.sleep(1)
            if self._status == self.STATUS_RUNNING:
                self._elapsed_sec += 1
                # Broadcast setiap detik agar frontend sync waktu elapsed
                self._broadcast_status()
