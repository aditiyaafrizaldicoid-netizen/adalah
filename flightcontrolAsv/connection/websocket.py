import json
import time
import threading
import websocket
from core.client import ASVController



class ASVWebSocketClient:
    """
    WebSocket client yang menghubungkan Python flightcontrolAsv ke Go Backend.

    Format pesan yang diterima dari base station:
    {
        "type": "COMMAND",                  # Tipe pesan
        "cmd": {
            "action": "<nama_action>",       # Nama aksi yang akan dijalankan
            ... (parameter tambahan sesuai action)
        },
        "timestamp": 1234567890
    }

    Format pesan yang dikirim ke base station:
    - Telemetry  : { "type": "TELEMETRY", "payload": { ... } }
    - Channel ACK: { "type": "CHANNEL_CONFIG", "payload": { ... } }
    - Warning    : { "type": "WARNING", "payload": { level, code, message, timestamp } }
    - FC Disc    : { "type": "FC_DISCONNECTED" }
    """

    def __init__(self, asv: ASVController, ws_url: str = "ws://10.196.68.119:3000/api/v1/ws/asv", video_streamer=None):
        self.asv = asv
        self.ws_url = ws_url
        self.video_streamer = video_streamer
        self.ws = None
        self._is_running = False
        self._thread = None
        self._telemetry_thread = None
        self._fc_monitor_thread = None

        # State RC Override per-channel yang sedang aktif (persistent antar perintah)
        self._rc_state = [65535] * 18  # 18 channel, semua di-release default

        # Tracking status FC untuk deteksi disconnect
        self._fc_was_connected = False
        self._fc_monitor_lock = threading.Lock()
        self._send_lock = threading.Lock()  # Thread-safe lock untuk pengiriman pesan WebSocket


        # Reference ke VideoStreamer, TrackingController & SpeedScheduler
        self.video_streamer = None
        self.tracking_controller = None
        self.speed_scheduler = None
        self._camera_was_ok = False
        self.mission_engine = None

    def set_video_streamer(self, video_streamer):
        self.video_streamer = video_streamer
        # Daftarkan callback agar VideoStreamer memberi tahu kita saat kamera putus/nyambung
        if hasattr(video_streamer, 'set_status_callback'):
            video_streamer.set_status_callback(self._on_camera_status_change)

    def set_tracking_controller(self, tracking_controller):
        self.tracking_controller = tracking_controller
        print("[WS] TrackingController registered for live PID tuning")
        self.fetch_and_apply_pid_config()

    def set_speed_scheduler(self, speed_scheduler):
        self.speed_scheduler = speed_scheduler
        print("[WS] SpeedScheduler registered for live throttle scale tuning")

    def fetch_and_apply_pid_config(self):
        """Fetch PID & Motion parameters from backend database on startup."""
        import urllib.request
        import json
        try:
            url = "http://localhost:3000/api/v1/pid-config"
            req = urllib.request.Request(url, headers={"User-Agent": "ASVFlightController"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode('utf-8'))
                    if data.get("status") == "success" and data.get("data"):
                        cfg = data["data"]
                        f_speed = cfg.get("forward_speed")
                        if self.tracking_controller:
                            self.tracking_controller.update_pid_params(
                                kp=cfg.get("kp"),
                                ki=cfg.get("ki"),
                                kd=cfg.get("kd"),
                                forward_speed=f_speed,
                                max_turn_rate=cfg.get("max_turn_rate"),
                                align_threshold_px=cfg.get("align_threshold_px")
                            )
                        if self.speed_scheduler and f_speed is not None:
                            self.speed_scheduler.update_throttle_limit(f_speed)
                        print(f"[WS] 📥 Synced initial PID config from DB -> Speed/Throttle: {f_speed}, MaxTurn: {cfg.get('max_turn_rate')}deg/s")
        except Exception as e:
            print(f"[WS] Warning: Could not fetch initial PID config from DB ({e})")

    def set_mission_engine(self, mission_engine):
        self.mission_engine = mission_engine
        print("[WS] MissionEngine registered for autonomous mission control")

    def send_mission_status(self, status_dict: dict):
        """Kirim status misi terbaru ke Base Station."""
        self._send_ws({
            "type": "MISSION_STATUS",
            "payload": status_dict
        })




    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._run_ws, daemon=True)
        self._thread.start()

        self._telemetry_thread = threading.Thread(target=self._send_telemetry_loop, daemon=True)
        self._telemetry_thread.start()

        # Thread monitor untuk deteksi FC disconnect
        self._fc_monitor_thread = threading.Thread(target=self._fc_monitor_loop, daemon=True)
        self._fc_monitor_thread.start()

    def stop(self):
        self._is_running = False
        if self.ws:
            self.ws.close()

    def _run_ws(self):
        while self._is_running:
            print(f"[WS] Connecting to {self.ws_url}...")
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            self.ws.on_open = self._on_open
            self.ws.run_forever()
            if self._is_running:
                print("[WS] Reconnecting in 3 seconds...")
                time.sleep(3)

    def _on_open(self, ws):
        print("[WS] Connected to Backend")
        # Kirim channel config saat ini ke base station supaya UI sync
        self._send_channel_config_ack()
        # Kirim status FC saat ini ke base station
        if self.asv.is_connected():
            self._send_warning("info", "FC_CONNECTED", "Flight Controller terhubung ke Mini PC")
        else:
            self._send_warning("warning", "FC_DISCONNECTED_ON_CONNECT",
                               "⚠️ Flight Controller belum terdeteksi saat Mini PC terhubung ke base station")

    def _on_error(self, ws, error):
        print(f"[WS] Error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        print("[WS] Closed")

    # ------------------------------------------------------------------ #
    #  MESSAGE HANDLER                                                     #
    # ------------------------------------------------------------------ #

    def _on_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            # ---- Abaikan PING diam-diam ----
            if msg_type == "PING":
                return

            # ---- Semua perintah bertipe COMMAND ----
            if msg_type != "COMMAND":
                print(f"[WS] Unknown message type: {msg_type}")
                return

            cmd = data.get("cmd", {})
            action = cmd.get("action", "")
            print(f"[WS] Received command: action={action}")

            self._dispatch_action(action, cmd)

        except json.JSONDecodeError as e:
            print(f"[WS] JSON parse error: {e} | raw: {message[:200]}")
        except Exception as e:
            print(f"[WS] Error handling message: {e}")

    def _dispatch_action(self, action: str, cmd: dict):
        """Mendispatch action ke method yang sesuai. Semua parameter diambil dari cmd dict."""

        # --- ARM / DISARM ---
        if action == "arm":
            force = cmd.get("force", True)
            self.asv.arm(force=force)
            print(f"[WS] Command: ARM (force={force})")

        elif action == "disarm":
            force = cmd.get("force", True)
            self.asv.disarm(force=force)
            print(f"[WS] Command: DISARM (force={force})")



        # --- EMERGENCY STOP ---
        elif action == "emergency_stop":
            reason = cmd.get("reason", "unknown")
            print(f"[WS] ⚠️ EMERGENCY STOP diterima! Alasan: {reason}")
            self._execute_emergency_stop(reason)

        # --- MODE ---
        elif action == "set_mode":
            mode = cmd.get("mode", "")
            if mode:
                print(f"[WS] set_mode: Switching to {mode}...")
                self.asv.set_mode(mode)
            else:
                print("[WS] set_mode: parameter 'mode' tidak ada dalam cmd")

        # --- NAVIGASI (GUIDED MODE) ---
        elif action == "move_forward":
            speed = float(cmd.get("speed", 1.0))
            self.asv.move_forward(speed)

        elif action == "turn":
            speed = float(cmd.get("speed", 1.0))
            turn_rate = float(cmd.get("turn_rate_deg", 10.0))
            self.asv.turn(speed, turn_rate)

        elif action == "stop":
            self.asv.stop_movement()

        # --- UPDATE PID TRACKING TUNING ---
        elif action == "update_pid":
            kp = cmd.get("kp", None)
            ki = cmd.get("ki", None)
            kd = cmd.get("kd", None)
            speed = cmd.get("forward_speed", None)
            max_turn = cmd.get("max_turn_rate", None)
            align_tol = cmd.get("align_threshold_px", None)
            throttle = cmd.get("max_base_throttle", None) or cmd.get("throttle", None) or speed

            if self.tracking_controller:
                self.tracking_controller.update_pid_params(
                    kp=kp, ki=ki, kd=kd,
                    forward_speed=speed,
                    max_turn_rate=max_turn,
                    align_threshold_px=align_tol
                )
            if self.speed_scheduler and throttle is not None:
                self.speed_scheduler.update_throttle_limit(throttle)

            print(f"[WS] PID & Throttle parameters dynamically tuned -> Kp:{kp}, Ki:{ki}, Kd:{kd}, Speed/Throttle:{throttle}, MaxTurn:{max_turn}")

        # --- MANUAL CONTROL (Joystick / Gamepad MAVLink) ---

        elif action == "manual_control":
            x = int(cmd.get("x", 0))
            y = int(cmd.get("y", 0))
            z = int(cmd.get("z", 500))
            r = int(cmd.get("r", 0))
            buttons = int(cmd.get("buttons", 0))
            self.asv.send_manual_control(x, y, z, r, buttons)

        # --- RELEASE RC ---
        elif action == "release_rc":
            self._rc_state = [65535] * 18
            self.asv.release_rc()


        # --- CHANNEL MAP CONFIG (Dari base station) ---
        elif action == "set_channel_map":
            channel_map = cmd.get("channel_map", {})
            if channel_map:
                ok = self.asv.update_channel_config(channel_map)
                if ok:
                    # Kirim konfirmasi balik ke base station dengan config terbaru
                    self._send_channel_config_ack()
            else:
                print("[WS] set_channel_map: parameter 'channel_map' tidak ada dalam cmd")

        # --- REQUEST CHANNEL MAP (Base station minta sinkronisasi) ---
        elif action == "get_channel_map":
            self._send_channel_config_ack()



        # --- UPLOAD MISSION / WAYPOINTS (Dari Map UI) ---
        elif action == "upload_mission":
            waypoints = cmd.get("waypoints", [])
            if waypoints:
                ok = self.asv.upload_mission(waypoints)
                self._send_ws({
                    "type": "MISSION_UPDATE",
                    "payload": {"status": "UPLOADED" if ok else "FAILED", "count": len(waypoints)}
                })
                print(f"[WS] upload_mission: {len(waypoints)} waypoints uploaded (ok={ok})")

        # --- SAVE CURRENT WAYPOINT (Survey Mode - Tombol UI) ---
        elif action == "save_current_waypoint":
            t = self.asv.get_telemetry_dict()
            lat = t.get("lat")
            lng = t.get("lon")
            if lat and lng and lat != 0:
                wp = {"lat": lat, "lng": lng, "seq": len(getattr(self.asv, '_saved_survey_waypoints', [])) + 1}
                if not hasattr(self.asv, '_saved_survey_waypoints'):
                    self.asv._saved_survey_waypoints = []
                self.asv._saved_survey_waypoints.append(wp)
                self._send_ws({
                    "type": "WAYPOINT_SAVED",
                    "payload": wp
                })
                print(f"[WS] 📍 Save Current Waypoint: {wp}")

        # --- SET RELATIVE METER WAYPOINTS ---
        elif action == "set_relative_waypoints":
            meter_list = cmd.get("meter_waypoints", [])
            if meter_list:
                from control.geodesy import LocalFrameConverter
                t = self.asv.get_telemetry_dict()
                home_lat = t.get("lat") or -7.9215169
                home_lng = t.get("lon") or 112.5973649
                heading = t.get("heading") or 0.0
                gps_wps = LocalFrameConverter.convert_meter_waypoints_to_gps(home_lat, home_lng, heading, meter_list)
                self.asv.upload_mission(gps_wps)
                self._send_ws({
                    "type": "MISSION_UPDATE",
                    "payload": {"status": "RELATIVE_CONVERTED", "waypoints": gps_wps}
                })
                print(f"[WS] 📐 Relative Meter Waypoints converted: {len(gps_wps)} points")

        # --- SET SINGLE PARAM ---
        elif action == "set_param":
            param_name = cmd.get("param_name", "")
            value = cmd.get("value", 0)
            if param_name:
                ok = self.asv.set_param(param_name, float(value))
                self._send_ws({
                    "type": "PARAM_SET_RESULT",
                    "payload": {"param_name": param_name, "value": value, "ok": ok}
                })
            else:
                print("[WS] set_param: 'param_name' tidak ditemukan dalam cmd")


        # --- VIDEO RECORDING (Tanpa Object Detection) ---
        elif action == "start_recording":
            width = cmd.get("width")
            height = cmd.get("height")
            if self.video_streamer:
                filename = self.video_streamer.start_recording(width=width, height=height)
                self._send_ws({
                    "type": "RECORDING_STATUS",
                    "payload": {
                        "is_recording": True,
                        "filename": filename,
                        "width": self.video_streamer.record_width,
                        "height": self.video_streamer.record_height
                    }
                })
            else:
                print("[WS] start_recording: video_streamer tidak terhubung pada ws_client")

        elif action == "stop_recording":
            if self.video_streamer:
                filename = self.video_streamer.stop_recording()
                self._send_ws({
                    "type": "RECORDING_STATUS",
                    "payload": {
                        "is_recording": False,
                        "filename": filename
                    }
                })
            else:
                print("[WS] stop_recording: video_streamer tidak terhubung pada ws_client")

        # --- MISSION ENGINE CONTROLS ---
        elif action == "load_mission":
            steps = cmd.get("steps", [])
            if self.mission_engine and steps:
                ok = self.mission_engine.load_mission(steps)
                self.send_mission_status(self.mission_engine.get_status_dict())
                print(f"[WS] Mission loaded with {len(steps)} steps (ok={ok})")
            else:
                print("[WS] ⚠️ load_mission: mission_engine tidak registered atau steps kosong!")

        elif action == "start_mission":
            steps = cmd.get("steps", [])
            if self.mission_engine:
                ok = self.mission_engine.start_mission(steps)
                self.send_mission_status(self.mission_engine.get_status_dict())
                print(f"[WS] Mission started (ok={ok}, steps={len(self.mission_engine._steps)})")
            else:
                print("[WS] ⚠️ start_mission: mission_engine tidak registered!")



        elif action == "pause_mission":
            if self.mission_engine:
                self.mission_engine.pause_mission()
                print("[WS] Mission paused")

        elif action == "resume_mission":
            if self.mission_engine:
                self.mission_engine.resume_mission()
                print("[WS] Mission resumed")

        elif action == "abort_mission":
            if self.mission_engine:
                self.mission_engine.abort_mission()
                print("[WS] Mission aborted")

        elif action == "reset_mission":
            if self.mission_engine:
                self.mission_engine.reset_mission()
                print("[WS] Mission reset")

        elif action == "get_mission_status":
            if self.mission_engine:
                self.send_mission_status(self.mission_engine.get_status_dict())



        elif action:
            print(f"[WS] Unknown action: {action}")

    # ------------------------------------------------------------------ #
    #  EMERGENCY STOP                                                      #
    # ------------------------------------------------------------------ #

    def _execute_emergency_stop(self, reason: str = "unknown"):
        """
        Hentikan kapal SEGERA: lepaskan semua RC override dan hentikan gerak.
        Kemudian kirim WARNING ke base station.
        """
        try:
            # Stop movement (set velocity = 0 via MAVLink)
            self.asv.stop_movement()

            print(f"[WS] ⛔ EMERGENCY STOP dieksekusi. Alasan: {reason}")


            # 3. Kirim WARNING ke base station agar operator tahu
            self._send_warning(
                level="critical",
                code="EMERGENCY_STOP_EXECUTED",
                message=f"⛔ EMERGENCY STOP dieksekusi di kapal! Alasan: {reason}. Semua thruster dimatikan."
            )
        except Exception as e:
            print(f"[WS] Error saat emergency stop: {e}")

    # ------------------------------------------------------------------ #
    #  FC DISCONNECT MONITOR                                               #
    # ------------------------------------------------------------------ #

    def _fc_monitor_loop(self):
        """
        Thread terpisah yang memonitor koneksi antara Mini PC dan Flight Controller (Pixhawk).
        Jika FC disconnect → kirim FC_DISCONNECTED + WARNING ke base station.
        Jika FC reconnect → kirim FC_CONNECTED ke base station.
        """
        print("[WS] FC monitor thread started")
        CHECK_INTERVAL = 1.0  # Cek setiap 1 detik

        while self._is_running:
            try:
                fc_connected = self.asv.is_connected()

                with self._fc_monitor_lock:
                    prev_connected = self._fc_was_connected

                if fc_connected != prev_connected:
                    with self._fc_monitor_lock:
                        self._fc_was_connected = fc_connected

                    if not fc_connected:
                        # FC baru saja PUTUS
                        print("[WS] ⚠️ FC DISCONNECT terdeteksi! Mengirim notifikasi ke base station...")
                        # Kirim pesan FC_DISCONNECTED khusus (backend juga handle ini)
                        self._send_ws({"type": "FC_DISCONNECTED"})
                        # Kirim WARNING agar UI bisa menampilkannya di alerts panel
                        self._send_warning(
                            level="critical",
                            code="FC_DISCONNECTED",
                            message="⚠️ KRITIS: Mini PC terputus dari Flight Controller! Kapal tidak dapat dikontrol."
                        )
                        # Emergency stop sebagai tindakan pengamanan
                        self._execute_emergency_stop("fc_disconnected")

                    else:
                        # FC baru saja TERHUBUNG kembali
                        print("[WS] ✅ FC RECONNECTED! Mengirim notifikasi ke base station...")
                        self._send_warning(
                            level="info",
                            code="FC_RECONNECTED",
                            message="✅ Flight Controller kembali terhubung ke Mini PC."
                        )

            except Exception as e:
                print(f"[WS] FC monitor error: {e}")

            time.sleep(CHECK_INTERVAL)

    # ------------------------------------------------------------------ #
    #  CAMERA STATUS CALLBACK                                              #
    # ------------------------------------------------------------------ #

    def _on_camera_status_change(self, is_ok: bool, reason: str = ""):
        """
        Dipanggil oleh VideoStreamer saat status kamera berubah.
        is_ok=False → kamera putus, is_ok=True → kamera kembali
        """
        if not is_ok:
            if self._camera_was_ok is not False:
                self._camera_was_ok = False
                print(f"[WS] 📷 Kamera PUTUS terdeteksi oleh VideoStreamer! ({reason})")
                self._send_warning(
                    level="critical",
                    code="CAMERA_LOST",
                    message=f"🎥 KRITIS: Kamera terputus di Mini PC! ({reason}) Menghentikan kapal..."
                )
                # Emergency stop saat kamera putus
                self._execute_emergency_stop("camera_lost")

        else:
            if self._camera_was_ok is not True:
                self._camera_was_ok = True
                print(f"[WS] 📷 Kamera kembali terhubung!")
                self._send_warning(
                    level="info",
                    code="CAMERA_RESTORED",
                    message="📷 Kamera berhasil terhubung kembali di Mini PC."
                )

    # ------------------------------------------------------------------ #
    #  SEND HELPERS                                                        #
    # ------------------------------------------------------------------ #

    def _send_ws(self, data: dict):
        """Helper: kirim dict sebagai JSON ke base station via WebSocket (Thread-Safe)."""
        with self._send_lock:
            if self.ws and self.ws.sock and self.ws.sock.connected:
                try:
                    self.ws.send(json.dumps(data))
                except Exception as e:
                    print(f"[WS] Error sending message: {e}")


    def _send_warning(self, level: str, code: str, message: str):
        """
        Kirim pesan WARNING terformat ke base station.
        level: 'critical' | 'warning' | 'info'
        code: kode unik, misal 'FC_DISCONNECTED', 'CAMERA_LOST'
        """
        self._send_ws({
            "type": "WARNING",
            "payload": {
                "level": level,
                "code": code,
                "message": message,
                "timestamp": int(time.time() * 1000)
            }
        })
        print(f"[WS] WARNING sent → [{level.upper()}] {code}: {message}")

    def _send_channel_config_ack(self):
        """Kirim channel config saat ini ke base station (untuk sinkronisasi UI)."""
        self._send_ws({
            "type": "CHANNEL_CONFIG",
            "payload": self.asv.get_channel_config()
        })
        print("[WS] Sent CHANNEL_CONFIG ack to base station")

    def _send_telemetry_loop(self):
        """Loop 100ms untuk mengirim telemetri ke base station."""
        while self._is_running:
            if self.ws and self.ws.sock and self.ws.sock.connected:
                t = self.asv.get_telemetry_dict()
                try:
                    payload = {
                        "lat": t.get("lat"),
                        "lng": t.get("lon"),
                        "heading": t.get("heading"),
                        "sog": t.get("ground_speed"),
                        "pitch": t.get("pitch"),
                        "roll": t.get("roll"),
                        "yaw": t.get("yaw"),
                        "battery_pct": t.get("battery_remaining"),
                        "battery_volt": t.get("battery_voltage"),
                        "satellites": t.get("satellites_visible", 0),  # FIX: 0 bukan 10
                        "gps_fix": 3 if t.get("lat") else 0,
                        "is_armed": t.get("is_armed", False),
                        "mode": t.get("mode", "UNKNOWN"),
                        "is_connected": t.get("is_connected", False),
                        "camera_connected": self.video_streamer.is_camera_ok() if self.video_streamer else False,
                        "is_recording": self.video_streamer.is_recording if self.video_streamer else False,
                        "recording_filename": self.video_streamer.recording_filename if (self.video_streamer and self.video_streamer.is_recording) else "",
                        "recording_resolution": f"{self.video_streamer.record_width}x{self.video_streamer.record_height}" if (self.video_streamer and self.video_streamer.is_recording) else ""
                    }

                    self.ws.send(json.dumps({
                        "type": "TELEMETRY",
                        "payload": payload
                    }))
                except Exception as e:
                    print(f"[WS] Send error: {e}")
            time.sleep(0.1)  # Kirim setiap 100ms
