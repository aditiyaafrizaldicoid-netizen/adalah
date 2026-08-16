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
    GATE_IDENTITY_MAX_DIST_PX = 200

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
        # Steer yang dipertahankan selama TRANSITIONING
        self._transition_steer: float = 0.0

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
                elif step_type in (self.STEP_TYPE_HOLD, self.STEP_TYPE_TAKE_IMAGE):
                    # Pastikan mode GUIDED agar stop_movement() (send_velocity 0) efektif
                    if self.asv and self.asv.is_connected():
                        telemetry = self.asv.get_telemetry()
                        if telemetry.mode != "GUIDED":
                            print(f"[MissionEngine] 🔄 Switch mode → GUIDED untuk {step_type}...")
                            self.asv.set_mode("GUIDED")
                    self.asv.stop_movement()

            # ---- TRACKING_BUOY ----
            if step_type == self.STEP_TYPE_TRACKING_BUOY:
                return self._handle_tracking(step, gate_x, detected_balls or {"red": [], "green": []})

            # ---- GOTO_GPS ----
            elif step_type == self.STEP_TYPE_GOTO_GPS:
                return self._handle_goto_gps(step, frame, gate_x)

            # ---- TAKE_IMAGE ----
            elif step_type == self.STEP_TYPE_TAKE_IMAGE:
                return self._handle_take_image(step, frame, gate_x)

            # ---- HOLD ----
            elif step_type == self.STEP_TYPE_HOLD:
                return self._handle_hold(step, frame, gate_x)

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
                self._transition_steer = -abs(self.TRANSITION_LEAN_MAGNITUDE)
                self._gate_lock_state  = self.GATE_TRANSITIONING
                # Update posisi terakhir bola hijau yang terlihat (untuk tracking selama transition)
                self._locked_green_pos = (nearest_green[0], nearest_green[1])
                print(f"[GATE] LOCKED → TRANSITIONING (missing=LEFT/red, lean={self._transition_steer:+.2f})")
                label = f"GATE:TRANSITIONING(←) | TRACKING_BUOY ({pass_label} pass)"
                return self._transition_steer, throttle, label

            elif red_visible_locked and not green_visible_locked:
                # ★ Bola HIJAU (kanan) hilang duluan → condong ke KANAN
                self._missing_side     = "right"
                self._transition_steer = +abs(self.TRANSITION_LEAN_MAGNITUDE)
                self._gate_lock_state  = self.GATE_TRANSITIONING
                # Update posisi terakhir bola merah yang terlihat
                self._locked_red_pos   = (nearest_red[0], nearest_red[1])
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
                # Cek apakah bola hijau dari gerbang INI masih ada.
                nearest_green = self._find_nearest_ball(detected_balls.get("green", []), self._locked_green_pos)
                if nearest_green:
                    remaining_visible = True
                    self._locked_green_pos = (nearest_green[0], nearest_green[1])
            elif self._missing_side == "right":
                # Bola hijau sudah hilang, tinggal tunggu bola merah juga hilang.
                nearest_red = self._find_nearest_ball(detected_balls.get("red", []), self._locked_red_pos)
                if nearest_red:
                    remaining_visible = True
                    self._locked_red_pos = (nearest_red[0], nearest_red[1])

            if remaining_visible:
                # Bola tersisa masih ada di frame → pertahankan manuver condong
                lean_dir = "←" if self._missing_side == "left" else "→"
                label = f"GATE:TRANSITIONING({lean_dir}) | TRACKING_BUOY ({pass_label} pass)"
                return self._transition_steer, throttle, label
            else:
                # Bola terakhir juga hilang → gate CLEARED!
                self._gate_lock_state = self.GATE_CLEARED
                print("[GATE] TRANSITIONING → CLEARED (bola terakhir hilang)")
                return self._handle_gate_cleared(pass_label, step)

        elif self._gate_lock_state == self.GATE_CLEARED:
            # ── CLEARED ───────────────────────────────────────
            # Seharusnya sudah ditangani oleh _handle_gate_cleared(),
            # tapi guard di sini untuk keamanan.
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

    def _handle_goto_gps(self, step, frame, gate_x):
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
                return self.update_frame(frame, gate_x)

        return 0.0, 0.0, "GOTO_GPS"

    def _handle_take_image(self, step, frame, gate_x):
        """Handle TAKE_IMAGE step."""
        duration = float(step.get("duration_sec", 3.0))
        elapsed = time.time() - self._step_start_time

        if elapsed >= duration:
            print(f"[MissionEngine] ✅ TAKE_IMAGE selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x)

        return 0.0, 0.0, "TAKE_IMAGE"

    def _handle_hold(self, step, frame, gate_x):
        """Handle HOLD step."""
        duration = float(step.get("duration_sec", 5.0))
        elapsed = time.time() - self._step_start_time

        if elapsed >= duration:
            print(f"[MissionEngine] ✅ HOLD selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x)

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

        # Pastikan mode GUIDED
        if self.asv and self.asv.is_connected():
            telemetry = self.asv.get_telemetry()
            if telemetry.mode != "GUIDED":
                print("[MissionEngine] 🔄 Switch mode → GUIDED untuk CUSTOM_FORWARD...")
                self.asv.set_mode("GUIDED")

        # Kirim perintah gerak: maju dengan yaw rate = heading_offset_deg
        # NavigationControl.send_velocity() akan mengkonversi ke MAVLink (rad/s)
        self.asv.nav.send_velocity(
            forward_speed=speed_mps,
            turn_rate_deg=heading_offset_deg
        )

        remaining = max(0.0, duration_sec - elapsed)
        offset_label = f"+{heading_offset_deg:.1f}°" if heading_offset_deg >= 0 else f"{heading_offset_deg:.1f}°"
        label = (f"CUSTOM_FORWARD | spd={speed_mps:.1f}m/s offset={offset_label} "
                 f"rem={remaining:.1f}s")
        return 0.0, speed_mps, label

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

        # Pastikan mode GUIDED
        if self.asv and self.asv.is_connected():
            if getattr(telemetry, 'mode', 'GUIDED') != "GUIDED":
                print("[MissionEngine] 🔄 Switch mode → GUIDED untuk PRECISION_TURN...")
                self.asv.set_mode("GUIDED")

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
        self._gate_lock_state  = self.GATE_SEARCHING
        self._locked_red_pos   = None
        self._locked_green_pos = None
        self._missing_side     = None
        self._transition_steer = 0.0

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
