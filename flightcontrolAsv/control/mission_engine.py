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
"""

import time
import math
import threading
from typing import Optional, List, Dict, Any


class MissionEngine:
    """
    Finite State Machine untuk mengeksekusi mission steps otonom.

    Tidak melakukan kontrol motor secara langsung -- hanya memanggil
    metode ASVController (send_velocity, goto, stop_movement, dll).
    """

    STATUS_IDLE       = "IDLE"
    STATUS_RUNNING    = "RUNNING"
    STATUS_PAUSED     = "PAUSED"
    STATUS_FINISHED   = "FINISHED"
    STATUS_ABORTED    = "ABORTED"

    STEP_TYPE_TRACKING_BUOY = "TRACKING_BUOY"
    STEP_TYPE_GOTO_GPS      = "GOTO_GPS"
    STEP_TYPE_TAKE_IMAGE    = "TAKE_IMAGE"
    STEP_TYPE_HOLD          = "HOLD"
    STEP_TYPE_FINISH        = "FINISH"
    STEP_TYPE_START         = "START"

    # Radius acceptance untuk GOTO_GPS: dianggap tiba jika < X meter dari target
    ARRIVAL_RADIUS_M = 2.0

    def __init__(self, asv, tracker, tracking_controller):
        self.asv = asv
        self.tracker = tracker
        self.tracking_controller = tracking_controller

        self._steps: List[Dict[str, Any]] = []
        self._current_step_idx: int = 0
        self._status: str = self.STATUS_IDLE

        self._lock = threading.RLock()


        # Counter berapa gate PASSING sudah terjadi di step TRACKING saat ini
        self._buoy_pass_count: int = 0
        self._last_tracking_state: str = ""

        # Waktu mulai step TAKE_IMAGE / HOLD
        self._step_start_time: Optional[float] = None

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
                print("[MissionEngine] ⚠️ Tidak bisa load mission saat RUNNING!")
                return False
            self._steps = list(steps)
            self._current_step_idx = 0
            self._status = self.STATUS_IDLE
            self._buoy_pass_count = 0
            self._step_start_time = None
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
                self._step_start_time = None
                print(f"[MissionEngine] Mission loaded: {len(self._steps)} steps.")

            if not self._steps:
                print("[MissionEngine] ⚠️ Tidak ada mission steps yang di-load!")
                return False
            if self._status == self.STATUS_RUNNING:
                print("[MissionEngine] ⚠️ Mission sudah RUNNING!")
                return False
            self._status = self.STATUS_RUNNING
            self._current_step_idx = 0
            self._buoy_pass_count = 0
            self._step_start_time = time.time()
            self._mission_start_time = time.time()
            self._elapsed_sec = 0
            self._start_elapsed_timer()
            print(f"[MissionEngine] 🚀 MISSION STARTED! ({len(self._steps)} steps)")
            self._broadcast_status()
            return True


    def pause_mission(self):
        """Pause mission (ASV berhenti di posisi)."""
        with self._lock:
            if self._status != self.STATUS_RUNNING:
                return
            self._status = self.STATUS_PAUSED
            self._stop_elapsed_timer()
            self.asv.stop_movement()
            print("[MissionEngine] ⏸ MISSION PAUSED.")
            self._broadcast_status()

    def resume_mission(self):
        """Resume mission dari paused."""
        with self._lock:
            if self._status != self.STATUS_PAUSED:
                return
            self._status = self.STATUS_RUNNING
            self._step_start_time = time.time()
            self._start_elapsed_timer()
            print("[MissionEngine] ▶️ MISSION RESUMED.")
            self._broadcast_status()

    def abort_mission(self):
        """Batalkan mission dan stop kapal."""
        with self._lock:
            self._status = self.STATUS_ABORTED
            self._stop_elapsed_timer()
            self.asv.stop_movement()  # Hentikan gerak, JANGAN ubah mode
            print("[MissionEngine] 🛑 MISSION ABORTED!")
            self._broadcast_status()

    def reset_mission(self):
        """Reset semua state ke IDLE."""
        with self._lock:
            self._status = self.STATUS_IDLE
            self._current_step_idx = 0
            self._buoy_pass_count = 0
            self._step_start_time = None
            self._elapsed_sec = 0
            self._stop_elapsed_timer()
            print("[MissionEngine] 🔄 MISSION RESET.")
            self._broadcast_status()

    @property
    def status(self) -> str:
        return self._status

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
            if self._step_start_time and self._status == self.STATUS_RUNNING:
                step_elapsed = round(time.time() - self._step_start_time, 1)

            return {
                "status": self._status,
                "current_step_idx": self._current_step_idx,
                "current_step": current_step_info,
                "total_steps": len(self._steps),
                "elapsed_sec": self._elapsed_sec,
                "step_elapsed_sec": step_elapsed,
                "buoy_pass_count": self._buoy_pass_count,
            }


    # ------------------------------------------------------------------ #
    #  Frame Update Loop (dipanggil dari video_streamer callback ~30FPS)  #
    # ------------------------------------------------------------------ #

    def update_frame(self, frame, gate_x: Optional[float]):
        """
        Dipanggil oleh process_and_control() setiap frame.
        Return: (forward_speed, turn_rate_deg, step_type_label)
        """
        with self._lock:
            if self._status != self.STATUS_RUNNING:
                return 0.0, 0.0, "IDLE"

            if self._current_step_idx >= len(self._steps):
                self._finish_mission()
                return 0.0, 0.0, "FINISH"

            step = self._steps[self._current_step_idx]
            step_type = step.get("type", "")

            # ---- TRACKING_BUOY ----
            if step_type == self.STEP_TYPE_TRACKING_BUOY:
                return self._handle_tracking(step, gate_x)

            # ---- GOTO_GPS ----
            elif step_type == self.STEP_TYPE_GOTO_GPS:
                return self._handle_goto_gps(step)

            # ---- TAKE_IMAGE ----
            elif step_type == self.STEP_TYPE_TAKE_IMAGE:
                return self._handle_take_image(step)

            # ---- HOLD ----
            elif step_type == self.STEP_TYPE_HOLD:
                return self._handle_hold(step)

            # ---- START (warmup sebentar) ----
            elif step_type == self.STEP_TYPE_START:
                if self._step_start_time is None:
                    self._step_start_time = time.time()
                warmup_sec = step.get("duration_sec", 2.0)
                if time.time() - self._step_start_time >= warmup_sec:
                    self._advance_step()
                return 0.0, 0.0, "START"

            # ---- FINISH ----
            elif step_type == self.STEP_TYPE_FINISH:
                self._finish_mission()
                return 0.0, 0.0, "FINISH"

            else:
                # Unknown step — skip
                self._advance_step()
                return 0.0, 0.0, "UNKNOWN"

    # ------------------------------------------------------------------ #
    #  Step Handlers                                                      #
    # ------------------------------------------------------------------ #

    def _handle_tracking(self, step, gate_x):
        """Handle TRACKING_BUOY step."""
        target_passes = int(step.get("pass_count", 1))

        forward_speed, turn_rate, state = self.tracking_controller.compute_velocity(gate_x)

        # Deteksi transisi ke PASSING → increment pass count
        if state == "PASSING" and self._last_tracking_state != "PASSING":
            print(f"[MissionEngine] 🟢 Gate pass #{self._buoy_pass_count + 1}/{target_passes}")

        if state == "COOLDOWN" and self._last_tracking_state == "PASSING":
            self._buoy_pass_count += 1
            self._broadcast_status()
            if self._buoy_pass_count >= target_passes:
                print(f"[MissionEngine] ✅ TRACKING step selesai! {self._buoy_pass_count} gate dilewati.")
                self._buoy_pass_count = 0
                self._advance_step()
                return 0.0, 0.0, "TRACKING_BUOY"

        self._last_tracking_state = state
        return forward_speed, turn_rate, "TRACKING_BUOY"

    def _handle_goto_gps(self, step):
        """Handle GOTO_GPS step."""
        target_lat = float(step.get("lat", 0.0))
        target_lon = float(step.get("lon", 0.0))

        # Perintahkan Pixhawk menuju target GPS
        self.asv.goto(target_lat, target_lon)

        # Cek apakah sudah sampai (radius acceptance)
        telemetry = self.asv.get_telemetry()
        if telemetry.lat != 0 and telemetry.lon != 0:
            dist = self._haversine(telemetry.lat, telemetry.lon, target_lat, target_lon)
            print(f"[MissionEngine] 🧭 GOTO {step.get('name','?')}: dist={dist:.1f}m")
            if dist <= self.ARRIVAL_RADIUS_M:
                print(f"[MissionEngine] ✅ GOTO step selesai! Tiba di {step.get('name','?')}")
                self._advance_step()
                return 0.0, 0.0, "GOTO_GPS"

        return 0.0, 0.0, "GOTO_GPS"

    def _handle_take_image(self, step):
        """Handle TAKE_IMAGE step."""
        duration = float(step.get("duration_sec", 3.0))
        if self._step_start_time is None:
            self._step_start_time = time.time()
            self.asv.stop_movement()
            print(f"[MissionEngine] 📷 TAKE_IMAGE: berhenti & ambil foto selama {duration}s...")

        elapsed = time.time() - self._step_start_time
        if elapsed >= duration:
            print(f"[MissionEngine] ✅ TAKE_IMAGE selesai!")
            self._advance_step()

        return 0.0, 0.0, "TAKE_IMAGE"

    def _handle_hold(self, step):
        """Handle HOLD step."""
        duration = float(step.get("duration_sec", 5.0))
        if self._step_start_time is None:
            self._step_start_time = time.time()
            self.asv.stop_movement()
            print(f"[MissionEngine] ⚓ HOLD: berhenti selama {duration}s...")

        elapsed = time.time() - self._step_start_time
        if elapsed >= duration:
            print(f"[MissionEngine] ✅ HOLD selesai!")
            self._advance_step()

        return 0.0, 0.0, "HOLD"

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _advance_step(self):
        self._current_step_idx += 1
        self._step_start_time = None
        self._last_tracking_state = ""
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

