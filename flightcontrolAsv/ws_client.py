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
    """

    def __init__(self, asv: ASVController, ws_url: str = "ws://localhost:3000/api/v1/ws/asv", video_streamer=None):
        self.asv = asv
        self.ws_url = ws_url
        self.video_streamer = video_streamer
        self.ws = None
        self._is_running = False
        self._thread = None
        self._telemetry_thread = None

        # State RC Override per-channel yang sedang aktif (persistent antar perintah)
        self._rc_state = [65535] * 18  # 18 channel, semua di-release default

    def set_video_streamer(self, video_streamer):
        self.video_streamer = video_streamer

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._run_ws, daemon=True)
        self._thread.start()

        self._telemetry_thread = threading.Thread(target=self._send_telemetry_loop, daemon=True)
        self._telemetry_thread.start()

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

        # --- MODE ---
        elif action == "set_mode":
            mode = cmd.get("mode")
            if mode:
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

        # --- RESTORE FAILSAFE (Kembalikan ke default) ---
        elif action == "restore_failsafe":
            print("[WS] Memulihkan failsafe ke nilai default...")
            results = self.asv.restore_default_failsafe()
            self._send_ws({
                "type": "PARAM_SET_RESULT",
                "payload": {"action": "restore_failsafe", "results": results}
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
    #  SEND HELPERS                                                        #
    # ------------------------------------------------------------------ #

    def _send_ws(self, data: dict):
        """Helper: kirim dict sebagai JSON ke base station via WebSocket."""
        if self.ws and self.ws.sock and self.ws.sock.connected:
            try:
                self.ws.send(json.dumps(data))
            except Exception as e:
                print(f"[WS] Error sending message: {e}")

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
