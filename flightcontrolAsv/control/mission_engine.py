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

    STEP_TYPE_TRACKING_BUOY = "TRACKING_BUOY"
    STEP_TYPE_GOTO_GPS      = "GOTO_GPS"
    STEP_TYPE_TAKE_IMAGE    = "TAKE_IMAGE"
    STEP_TYPE_HOLD          = "HOLD"
    STEP_TYPE_FINISH        = "FINISH"
    STEP_TYPE_START         = "START"

    # Radius acceptance untuk GOTO_GPS: dianggap tiba jika < X meter dari target
    ARRIVAL_RADIUS_M = 2.0

    # ---- Gate Lock FSM States ----
    # SEARCHING        : Belum ada gate yang terkunci, mencari pasangan bola
    # LOCKED           : Pasangan bola gate saat ini terkunci, tracking midpoint normal
    # PASSING_LEFT_GONE: Bola kiri hilang duluan → manuver condong KIRI
    # PASSING_RIGHT_GONE: Bola kanan hilang duluan → manuver condong KANAN
    # CLEAR            : Kedua bola hilang, gate dilewati → reset ke SEARCHING
    GATE_STATE_SEARCHING          = "SEARCHING"
    GATE_STATE_LOCKED             = "LOCKED"
    GATE_STATE_PASSING_LEFT_GONE  = "PASSING_LEFT_GONE"
    GATE_STATE_PASSING_RIGHT_GONE = "PASSING_RIGHT_GONE"
    GATE_STATE_CLEAR              = "CLEAR"

    # Besaran steer manuver transisi (0.0–1.0 normalized)
    # Dikurangi dari bola yang tersisa: jika kanan masih ada → steer kiri sekian
    DEFAULT_TRANSITION_STEER = 0.35

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
        self._gate_in_view: bool = False  # True saat target sedang terlihat di kamera

        # ---- Gate Lock FSM state ----
        self._gate_state: str = self.GATE_STATE_SEARCHING
        # Arah steer manuver transisi: +1.0 = kanan, -1.0 = kiri
        self._transition_steer: float = 0.0

        # Waktu mulai step aktif & offset saat pause
        self._step_start_time: Optional[float] = None
        self._paused_step_elapsed: float = 0.0
        self._last_goto_time: float = 0.0

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
            self._gate_in_view = False
            self._gate_state = self.GATE_STATE_SEARCHING
            self._transition_steer = 0.0
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
                self._gate_in_view = False
                self._step_start_time = None
                self._paused_step_elapsed = 0.0
                print(f"[MissionEngine] Mission loaded: {len(self._steps)} steps.")

            if not self._steps:
                print("[MissionEngine] Tidak ada mission steps yang di-load!")
                return False
            if self._status == self.STATUS_RUNNING:
                print("[MissionEngine] Mission sudah RUNNING!")
                return False

            self._status = self.STATUS_RUNNING
            self._current_step_idx = 0
            self._buoy_pass_count = 0
            self._gate_in_view = False
            self._gate_state = self.GATE_STATE_SEARCHING
            self._transition_steer = 0.0
            self._step_start_time = None
            self._paused_step_elapsed = 0.0
            self._last_goto_time = 0.0
            self._mission_start_time = time.time()
            self._elapsed_sec = 0

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
            }

    # ------------------------------------------------------------------ #
    #  Frame Update Loop (dipanggil dari video_streamer callback ~30FPS)  #
    # ------------------------------------------------------------------ #

    def update_frame(self, frame, gate_x: Optional[float],
                     left_visible: bool = False, right_visible: bool = False):
        """
        Dipanggil oleh process_and_control() setiap frame.

        :param frame:         Frame kamera (numpy array)
        :param gate_x:        Koordinat X midpoint gate dari tracker (None jika tidak ada)
        :param left_visible:  True jika bola kiri (hijau/class 0) terdeteksi di frame
        :param right_visible: True jika bola kanan (merah/class 1) terdeteksi di frame
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
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch Flight Controller mode -> MANUAL for TRACKING_BUOY...")
                        self.asv.set_mode("MANUAL")
                elif step_type in (self.STEP_TYPE_HOLD, self.STEP_TYPE_TAKE_IMAGE):
                    self.asv.stop_movement()

            # ---- TRACKING_BUOY ----
            if step_type == self.STEP_TYPE_TRACKING_BUOY:
                return self._handle_tracking(step, gate_x, left_visible, right_visible)

            # ---- GOTO_GPS ----
            elif step_type == self.STEP_TYPE_GOTO_GPS:
                return self._handle_goto_gps(step, frame, gate_x, left_visible, right_visible)

            # ---- TAKE_IMAGE ----
            elif step_type == self.STEP_TYPE_TAKE_IMAGE:
                return self._handle_take_image(step, frame, gate_x, left_visible, right_visible)

            # ---- HOLD ----
            elif step_type == self.STEP_TYPE_HOLD:
                return self._handle_hold(step, frame, gate_x, left_visible, right_visible)

            # ---- START (warmup sebentar) ----
            elif step_type == self.STEP_TYPE_START:
                warmup_sec = float(step.get("duration_sec", 2.0))
                if time.time() - self._step_start_time >= warmup_sec:
                    self._advance_step()
                    return self.update_frame(frame, gate_x, left_visible, right_visible)
                return 0.0, 0.0, "START"

            # ---- FINISH ----
            elif step_type == self.STEP_TYPE_FINISH:
                self._finish_mission()
                return 0.0, 0.0, "FINISH"

            else:
                # Unknown step — skip
                self._advance_step()
                return self.update_frame(frame, gate_x, left_visible, right_visible)

    # ------------------------------------------------------------------ #
    #  Step Handlers                                                      #
    # ------------------------------------------------------------------ #

    def _handle_tracking(self, step, gate_x, left_visible: bool = False, right_visible: bool = False):
        """
        Handle TRACKING_BUOY step menggunakan Gate Lock FSM.

        Gate Lock FSM States:
          SEARCHING        → mencari pasangan bola (kedua bola terlihat)
          LOCKED           → pasangan terkunci, tracking midpoint normal
          PASSING_LEFT_GONE  → bola kiri hilang duluan, steer condong kiri
          PASSING_RIGHT_GONE → bola kanan hilang duluan, steer condong kanan
          CLEAR            → kedua bola hilang, gate dihitung dilewati
        """
        target_pass_count = int(step.get("pass_count", 0))  # 0 = tidak pakai counter, pakai duration
        duration = float(step.get("duration_sec", 0.0))     # 0 = tidak pakai duration, pakai counter
        transition_steer = float(step.get("transition_steer", self.DEFAULT_TRANSITION_STEER))

        # --- Cek kondisi selesai berdasarkan pass_count ---
        if target_pass_count > 0 and self._buoy_pass_count >= target_pass_count:
            print(f"[MissionEngine] ✅ TRACKING_BUOY selesai! Pass count: {self._buoy_pass_count}/{target_pass_count}")
            self._gate_in_view = False
            self._gate_state = self.GATE_STATE_SEARCHING
            self._advance_step()
            return 0.0, 0.0, "TRACKING_BUOY"

        # --- Cek kondisi selesai berdasarkan duration (fallback jika pass_count tidak diset) ---
        if target_pass_count == 0 and duration > 0 and self._step_start_time and (time.time() - self._step_start_time >= duration):
            print(f"[MissionEngine] ✅ TRACKING_BUOY selesai! Durasi {duration}s terpenuhi.")
            self._gate_in_view = False
            self._gate_state = self.GATE_STATE_SEARCHING
            self._advance_step()
            return 0.0, 0.0, "TRACKING_BUOY"

        # Pastikan FC selalu berada di mode MANUAL saat menjalankan TRACKING_BUOY
        if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
            print("[MissionEngine] 🔄 Automatic mode switch to MANUAL for TRACKING_BUOY...")
            self.asv.set_mode("MANUAL")

        thr = self.speed_scheduler.max_base_throttle
        pass_label = f"{self._buoy_pass_count}/{target_pass_count}" if target_pass_count > 0 else str(self._buoy_pass_count)

        # ================================================================
        #  Gate Lock FSM
        # ================================================================

        # ---------- STATE: SEARCHING ----------
        if self._gate_state == self.GATE_STATE_SEARCHING:
            if left_visible and right_visible:
                # Kedua bola terdeteksi → kunci pasangan gate ini
                self._gate_state = self.GATE_STATE_LOCKED
                self._gate_in_view = True
                print(f"[MissionEngine] 🔒 Gate LOCKED! (pass #{pass_label})")
            # Selama SEARCHING, boleh pakai gate_x normal dari tracker
            if gate_x is not None:
                steer = self.tracking_controller.compute_normalized_steering(gate_x)
                return steer, thr, f"TRACKING_BUOY [SEARCHING] ({pass_label} pass)"
            else:
                return 0.0, 0.0, f"🔴 SEARCHING: tidak ada gate terdeteksi ({pass_label} pass)"

        # ---------- STATE: LOCKED ----------
        elif self._gate_state == self.GATE_STATE_LOCKED:
            if left_visible and right_visible:
                # Kedua bola masih terlihat → tracking midpoint normal
                steer = self.tracking_controller.compute_normalized_steering(gate_x) if gate_x is not None else 0.0
                return steer, thr, f"TRACKING_BUOY [LOCKED] ({pass_label} pass)"

            elif not left_visible and right_visible:
                # Bola KIRI hilang duluan → mulai manuver condong KIRI
                self._gate_state = self.GATE_STATE_PASSING_LEFT_GONE
                self._transition_steer = -transition_steer  # negatif = belok kiri
                print(f"[MissionEngine] 🔄 PASSING: Bola KIRI hilang → Steer kiri ({self._transition_steer:.2f})")
                return self._transition_steer, thr, f"TRACKING_BUOY [PASSING_LEFT_GONE] ({pass_label} pass)"

            elif left_visible and not right_visible:
                # Bola KANAN hilang duluan → mulai manuver condong KANAN
                self._gate_state = self.GATE_STATE_PASSING_RIGHT_GONE
                self._transition_steer = +transition_steer  # positif = belok kanan
                print(f"[MissionEngine] 🔄 PASSING: Bola KANAN hilang → Steer kanan ({self._transition_steer:.2f})")
                return self._transition_steer, thr, f"TRACKING_BUOY [PASSING_RIGHT_GONE] ({pass_label} pass)"

            else:
                # Kedua bola tiba-tiba hilang bersamaan dari state LOCKED
                # Anggap gate selesai dilewati
                self._gate_state = self.GATE_STATE_CLEAR
                print(f"[MissionEngine] ⚡ Kedua bola hilang bersamaan dari LOCKED → langsung CLEAR")
                # Jatuh ke handler CLEAR di bawah

        # ---------- STATE: PASSING_LEFT_GONE ----------
        #  Bola kiri sudah hilang, tunggu bola kanan juga hilang.
        #  DILARANG menggunakan gate_x dari tracker (bisa salah pasang dengan gate berikutnya).
        if self._gate_state == self.GATE_STATE_PASSING_LEFT_GONE:
            if right_visible:
                # Bola kanan masih terlihat → pertahankan steer condong kiri
                return self._transition_steer, thr, f"TRACKING_BUOY [PASSING_LEFT_GONE] ({pass_label} pass)"
            else:
                # Bola kanan juga sudah hilang → gate berhasil dilewati
                self._gate_state = self.GATE_STATE_CLEAR
                print(f"[MissionEngine] ✅ Gate CLEAR! (bola kanan hilang). Transisi ke SEARCHING.")
                # Jatuh ke handler CLEAR di bawah

        # ---------- STATE: PASSING_RIGHT_GONE ----------
        #  Bola kanan sudah hilang, tunggu bola kiri juga hilang.
        #  DILARANG menggunakan gate_x dari tracker.
        if self._gate_state == self.GATE_STATE_PASSING_RIGHT_GONE:
            if left_visible:
                # Bola kiri masih terlihat → pertahankan steer condong kanan
                return self._transition_steer, thr, f"TRACKING_BUOY [PASSING_RIGHT_GONE] ({pass_label} pass)"
            else:
                # Bola kiri juga sudah hilang → gate berhasil dilewati
                self._gate_state = self.GATE_STATE_CLEAR
                print(f"[MissionEngine] ✅ Gate CLEAR! (bola kiri hilang). Transisi ke SEARCHING.")
                # Jatuh ke handler CLEAR di bawah

        # ---------- STATE: CLEAR (transisi instan) ----------
        if self._gate_state == self.GATE_STATE_CLEAR:
            self._buoy_pass_count += 1
            self._gate_in_view = False
            self._gate_state = self.GATE_STATE_SEARCHING
            self._transition_steer = 0.0
            print(f"[MissionEngine] 🏁 Gate PASSED! Count: {self._buoy_pass_count}/{target_pass_count} → 🔍 SEARCHING gate berikutnya...")
            self._broadcast_status()
            return 0.0, 0.0, f"TRACKING_BUOY [SEARCHING] ({self._buoy_pass_count}/{target_pass_count} pass)"

        # Fallback (seharusnya tidak tercapai)
        return 0.0, 0.0, f"TRACKING_BUOY [UNKNOWN_STATE] ({pass_label} pass)"

    def _handle_goto_gps(self, step, frame, gate_x, left_visible: bool = False, right_visible: bool = False):
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
                return self.update_frame(frame, gate_x, left_visible, right_visible)

        return 0.0, 0.0, "GOTO_GPS"

    def _handle_take_image(self, step, frame, gate_x, left_visible: bool = False, right_visible: bool = False):
        """Handle TAKE_IMAGE step."""
        duration = float(step.get("duration_sec", 3.0))
        elapsed = time.time() - self._step_start_time

        if elapsed >= duration:
            print(f"[MissionEngine] ✅ TAKE_IMAGE selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x, left_visible, right_visible)

        return 0.0, 0.0, "TAKE_IMAGE"

    def _handle_hold(self, step, frame, gate_x, left_visible: bool = False, right_visible: bool = False):
        """Handle HOLD step."""
        duration = float(step.get("duration_sec", 5.0))
        elapsed = time.time() - self._step_start_time

        if elapsed >= duration:
            print(f"[MissionEngine] ✅ HOLD selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x, left_visible, right_visible)

        return 0.0, 0.0, "HOLD"

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _advance_step(self):
        self._current_step_idx += 1
        self._step_start_time = None
        self._paused_step_elapsed = 0.0
        self._last_goto_time = 0.0
        # Reset Gate FSM state untuk step tracking berikutnya
        self._gate_state = self.GATE_STATE_SEARCHING
        self._transition_steer = 0.0
        self._gate_in_view = False

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

