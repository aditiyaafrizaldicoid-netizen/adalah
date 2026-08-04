import json
import time
import threading
import websocket
from client import ASVController


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

        # Tracking status kamera untuk deteksi putus
        self._camera_was_ok = False

    def set_video_streamer(self, video_streamer):
        self.video_streamer = video_streamer
        # Daftarkan callback agar VideoStreamer memberi tahu kita saat kamera putus/nyambung
        if hasattr(video_streamer, 'set_status_callback'):
            video_streamer.set_status_callback(self._on_camera_status_change)

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
            force = bool(cmd.get("force", False))
            self.asv.arm(force=force)
            print(f"[WS] ARM {'(FORCE)' if force else ''}")

        elif action == "disarm":
            force = bool(cmd.get("force", False))
            self.asv.disarm(force=force)
            print(f"[WS] DISARM {'(FORCE)' if force else ''}")

        # --- EMERGENCY STOP ---
        elif action == "emergency_stop":
            reason = cmd.get("reason", "unknown")
            print(f"[WS] ⚠️ EMERGENCY STOP diterima! Alasan: {reason}")
            self._execute_emergency_stop(reason)

        # --- MODE ---
        elif action == "set_mode":
            mode = cmd.get("mode")
            if mode:
                mode_upper = mode.upper()
                # Mode GUIDED/AUTO/LOITER butuh SERVO_FUNCTION = RCPassThru (1) agar MAVLink bisa control servo.
                # Mode MANUAL/HOLD butuh SERVO_FUNCTION = Throttle/GroundSteering agar RC fisik bekerja.
                AUTONOMOUS_MODES = {"GUIDED", "AUTO", "LOITER", "RTL", "SMART_RTL", "FOLLOW"}
                RC_PHYSICAL_MODES = {"MANUAL", "HOLD", "ACRO", "STEERING"}

                if mode_upper in AUTONOMOUS_MODES:
                    print(f"[WS] set_mode: Switching to {mode_upper} — applying No-RC mode (RCPassThru) first...")
                    self.asv.apply_no_rc_mode()
                    import time; time.sleep(0.3)  # Beri waktu Pixhawk untuk update parameter
                elif mode_upper in RC_PHYSICAL_MODES:
                    print(f"[WS] set_mode: Switching to {mode_upper} — restoring RC physical mode...")
                    self.asv.apply_rc_mode()
                    import time; time.sleep(0.3)

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

        # --- RC OVERRIDE (raw channel list) ---
        elif action == "rc_override":
            channels = cmd.get("channels", [])
            if channels:
                self.asv.send_rc_override(channels)
            else:
                print("[WS] rc_override: parameter 'channels' tidak ada dalam cmd")

        # --- MANUAL CONTROL (Joystick / Gamepad) ---
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

        # --- SET SERVO (satu channel, via RC override agar tidak diblokir FC) ---
        elif action == "set_servo":
            channel = int(cmd.get("channel", 0))
            pwm = int(cmd.get("pwm", 1500))
            if 1 <= channel <= 18:
                # Update rc_state agar tidak mengganggu channel lain
                self._rc_state[channel - 1] = pwm
                self.asv.send_rc_override(self._rc_state)
                print(f"[WS] set_servo: ch{channel} = {pwm} µs via RC Override")
            else:
                print(f"[WS] set_servo: channel {channel} tidak valid (harus 1-18)")

        # --- DRIVE VECTORED (Thruster L/R + Servo L/R sekaligus) ---
        elif action == "drive_vectored":
            throttle_left = int(cmd.get("throttle_left", 1500))
            throttle_right = int(cmd.get("throttle_right", 1500))
            servo_left = int(cmd.get("servo_left", 1500))
            servo_right = int(cmd.get("servo_right", 1500))
            self.asv.drive_dual_vectored(throttle_left, throttle_right, servo_left, servo_right)

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

        # --- APPLY NO-RC MODE (Disable semua RC failsafe via PARAM_SET) ---
        elif action == "apply_no_rc_mode":
            print("[WS] Menerapkan konfigurasi No-RC Mode ke Pixhawk...")
            results = self.asv.apply_no_rc_mode()
            self._send_ws({
                "type": "PARAM_SET_RESULT",
                "payload": {"action": "apply_no_rc_mode", "results": results}
            })

        # --- RESTORE FAILSAFE / APPLY RC MODE (Kembalikan ke remote RC fisik) ---
        elif action in ("restore_failsafe", "apply_rc_mode"):
            print("[WS] Menerapkan konfigurasi RC Mode (Physical RC) ke Pixhawk...")
            results = self.asv.apply_rc_mode()
            self._send_ws({
                "type": "PARAM_SET_RESULT",
                "payload": {"action": action, "results": results}
            })

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
            # 1. Lepaskan semua RC override (thruster & servo kembali ke neutral)
            self._rc_state = [65535] * 18
            self.asv.release_rc()

            # 2. Stop movement (set velocity = 0 via MAVLink untuk mode GUIDED)
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
        if not is_ok and self._camera_was_ok:
            self._camera_was_ok = False
            print(f"[WS] 📷 Kamera PUTUS terdeteksi oleh VideoStreamer! ({reason})")
            self._send_warning(
                level="critical",
                code="CAMERA_LOST",
                message=f"🎥 KRITIS: Kamera terputus di Mini PC! ({reason}) Menghentikan kapal..."
            )
            # Emergency stop saat kamera putus
            self._execute_emergency_stop("camera_lost")

        elif is_ok and not self._camera_was_ok:
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
        """Helper: kirim dict sebagai JSON ke base station via WebSocket."""
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
