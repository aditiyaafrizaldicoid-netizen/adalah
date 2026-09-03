import json
import os
import time
import threading
import websocket
from core.client import ASVController
from control import manual_source
from vision import gate_convention


def _with_asv_token(url: str) -> str:
    """
    Sisipkan ASV_WS_TOKEN ke query string kalau kunci itu diisi di .env.

    Kunci ini memagari /ws/asv di backend: tanpa itu siapa pun yang bisa menjangkau
    base station dapat menyamar sebagai kapal dan menyuntikkan telemetri palsu.
    Dipakai lewat query string karena handshake WebSocket tidak membawa header
    Authorization — sisi Go memeriksanya di WSHandler.Upgrade().

    KOSONG = tidak disisipkan apa-apa, dan backend yang juga tidak menyetel
    ASV_WS_TOKEN akan menerima koneksi seperti sebelumnya. Itu disengaja supaya
    kapal yang belum di-deploy ulang tidak mendadak gagal konek; isi di KEDUA sisi
    untuk mengaktifkan pemeriksaannya.
    """
    token = os.getenv("ASV_WS_TOKEN", "").strip()
    if not token:
        return url
    from urllib.parse import quote
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}token={quote(token, safe='')}"


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
    - Manual src : { "type": "MANUAL_SOURCE", "payload": { source, ok, requested } }
    - Warning    : { "type": "WARNING", "payload": { level, code, message, timestamp } }
    - FC Disc    : { "type": "FC_DISCONNECTED" }
    """

    def __init__(self, asv: ASVController, ws_url: str = None, video_streamer=None):
        self.asv = asv
        # Default lama adalah IP mentah dari jaringan yang sudah tidak ada
        # ("ws://10.196.68.119:3000"). Kalau pemanggil lupa mengoper ws_url,
        # klien diam-diam menembak alamat asing dan gagal tanpa sebab yang jelas.
        # Sekarang jatuhnya ke ASV_WS_URL — sumber yang sama dengan main.py.
        self.ws_url = ws_url or os.getenv("ASV_WS_URL")
        if not self.ws_url:
            raise ValueError(
                "Alamat WebSocket base station tidak diketahui: oper ws_url, "
                "atau isi ASV_WS_URL di flightcontrolAsv1/.env"
            )
        self.ws_url = _with_asv_token(self.ws_url)
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
        self.tracker = None
        self._camera_was_ok = False
        self.mission_engine = None
        # Diisi main.py kalau switch sumber kendali di remote diaktifkan. Statusnya
        # ikut telemetri supaya dashboard bisa menjelaskan kenapa tombol sumber
        # kendali di sana "membalik sendiri" — tanpa itu, terlihat seperti rusak.
        self.rc_source_switch = None
        # Diisi main.py. Geofence perlu tahu kapan misi dimulai supaya bisa
        # mengunci pusat batasnya di posisi kapal saat itu.
        self.geofence = None

        # State kalibrasi IMU
        self._imu_calibrating = False
        self._imu_cal_step = 0

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

    def set_tracker(self, tracker):
        self.tracker = tracker
        print("[WS] BallTracker registered for live detection noise-floor tuning")

    def fetch_and_apply_pid_config(self):
        """Fetch PID & Motion parameters from backend database on startup."""
        import urllib.request
        import json
        import os
        # Sama seperti main.py: WAJIB dari .env, bukan hardcode localhost — di kapal
        # backend ada di base station. Lihat catatan panjang di main.py.
        try:
            url = os.getenv("ASV_PID_CONFIG_URL", "http://localhost:3000/api/v1/pid-config")
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
                        min_area = cfg.get("min_detection_area_px2")
                        if self.tracker and min_area is not None:
                            self.tracker.set_min_detection_area(min_area)
                        # Lintasan arena juga menumpang baris config yang sama.
                        # Tanpa ini, kapal yang di-restart di tepi danau diam-diam
                        # kembali ke Lintasan B — dan operator baru sadar setelah
                        # kapal membanting ke arah yang salah pada bola pertama.
                        lintasan = cfg.get("track")
                        if lintasan:
                            if gate_convention.set_lintasan(lintasan):
                                print(f"[WS] 🔀 Lintasan dari DB → {lintasan}")
                            elif str(lintasan).strip().upper() not in gate_convention.daftar_lintasan():
                                print(f"[WS] ⚠️ Lintasan '{lintasan}' dari DB tidak "
                                      f"dikenal — tetap di "
                                      f"{gate_convention.lintasan_aktif()}")

                        # Geofence menumpang baris config yang sama, jadi ikut
                        # terbawa tanpa permintaan HTTP tambahan.
                        if self.geofence is not None and cfg.get("geofence_radius_m") is not None:
                            self.geofence.configure(
                                enabled=cfg.get("geofence_enabled"),
                                lat=cfg.get("geofence_lat"),
                                lon=cfg.get("geofence_lon"),
                                radius_m=cfg.get("geofence_radius_m"),
                            )
                        print(f"[WS] 📥 Synced initial PID config from DB -> Speed/Throttle: {f_speed}, MaxTurn: {cfg.get('max_turn_rate')}deg/s, MinDetectionArea: {min_area}px²")
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
        # Daftarkan callback STATUSTEXT untuk monitoring kalibrasi IMU
        self.asv.state.set_statustext_callback(self._on_statustext)

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
            min_detection_area = cmd.get("min_detection_area_px2", None)

            if self.tracking_controller:
                self.tracking_controller.update_pid_params(
                    kp=kp, ki=ki, kd=kd,
                    forward_speed=speed,
                    max_turn_rate=max_turn,
                    align_threshold_px=align_tol
                )
            if self.speed_scheduler and throttle is not None:
                self.speed_scheduler.update_throttle_limit(throttle)
            if self.tracker and min_detection_area is not None:
                self.tracker.set_min_detection_area(min_detection_area)

            print(f"[WS] PID & Throttle parameters dynamically tuned -> Kp:{kp}, Ki:{ki}, Kd:{kd}, Speed/Throttle:{throttle}, MaxTurn:{max_turn}, MinDetectionArea:{min_detection_area}")

        # --- MANUAL CONTROL (Joystick / Gamepad MAVLink) ---

        elif action == "manual_control":
            x = int(cmd.get("x", 0))
            y = int(cmd.get("y", 0))
            z = int(cmd.get("z", 500))
            r = int(cmd.get("r", 0))
            buttons = int(cmd.get("buttons", 0))
            self.asv.send_manual_control(x, y, z, r, buttons)

        # --- SUMBER KENDALI MANUAL (Mini PC vs Remote RC fisik) ---
        elif action == "set_manual_source":
            self._handle_set_manual_source(cmd.get("source"))

        elif action == "get_manual_source":
            self._send_manual_source_ack(ok=True, requested=None)

        # --- RELEASE RC ---
        elif action == "release_rc":
            # Pelepasan tingkat rendah SAJA — tidak memindah sumber kendali, jadi frame
            # berikutnya dari main.py akan merebut override kembali. Untuk menyerahkan
            # kendali ke operator remote, pakai action 'set_manual_source'.
            self._rc_state = [manual_source.RC_IGNORE] * 18
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

        # --- STREAMING ON/OFF TOGGLE ---
        elif action == "start_streaming":
            if self.video_streamer:
                self.video_streamer.start_streaming()
                self._send_ws({
                    "type": "STREAMING_STATUS",
                    "payload": {"is_streaming": True}
                })
                print("[WS] 🟢 Streaming diaktifkan oleh base station")
            else:
                print("[WS] start_streaming: video_streamer tidak terhubung pada ws_client")

        elif action == "stop_streaming":
            if self.video_streamer:
                self.video_streamer.stop_streaming()
                self._send_ws({
                    "type": "STREAMING_STATUS",
                    "payload": {"is_streaming": False}
                })
                print("[WS] 🔴 Streaming dimatikan oleh base station")
            else:
                print("[WS] stop_streaming: video_streamer tidak terhubung pada ws_client")

        # --- MISSION ENGINE CONTROLS ---
        elif action == "load_mission":
            steps = cmd.get("steps", [])
            self._peringatkan_urutan_photo_box(steps)
            self._peringatkan_celah_box(steps)
            if self.mission_engine and steps:
                ok = self.mission_engine.load_mission(steps)
                self.send_mission_status(self.mission_engine.get_status_dict())
                print(f"[WS] Mission loaded with {len(steps)} steps (ok={ok})")
            else:
                print("[WS] ⚠️ load_mission: mission_engine tidak registered atau steps kosong!")

        elif action == "start_mission":
            steps = cmd.get("steps", [])
            if not self.asv.minipc_has_control():
                # Menolak di sini, bukan membiarkan misi jalan lalu semua perintah
                # geraknya diam-diam diblokir satu per satu: operator harus tahu kenapa
                # kapalnya tidak bergerak, bukan menebak-nebak.
                print("[WS] ⛔ start_mission DITOLAK — kendali sedang di REMOTE RC. "
                      "Kembalikan ke mini PC dulu dari panel Manual Control.")
                self._send_ws({
                    "type": "WARNING",
                    "payload": {
                        "level": "warning",
                        "code": "MISSION_BLOCKED_REMOTE",
                        "message": "Misi tidak dijalankan: kendali sedang dipegang remote RC. "
                                   "Kembalikan sumber kendali ke Mini PC dulu.",
                        "timestamp": time.time(),
                    }
                })
            elif self.mission_engine:
                self._peringatkan_urutan_photo_box(steps or self.mission_engine._steps)
                self._peringatkan_celah_box(steps or self.mission_engine._steps)

                # Geofence mengunci pusat batasnya di sini, dan berhak MENOLAK
                # keberangkatan kalau kapal sudah di luar batas sebelum mulai —
                # jauh lebih baik ketahuan sekarang daripada dibatalkan 2 detik
                # setelah berangkat.
                if self.geofence is not None:
                    boleh, alasan = self.geofence.on_mission_started()
                    if not boleh:
                        print(f"[WS] ⛔ start_mission DITOLAK geofence: {alasan}")
                        self._send_warning("warning", "GEOFENCE_TOLAK_START",
                                           f"Misi tidak dijalankan. {alasan} "
                                           f"Bawa kapal ke dalam batas dulu.")
                        return

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



        # --- CAMERA PARAMS ---
        elif action == "set_camera_params":
            if self.video_streamer:
                camera_key = cmd.get("camera", "surface")
                brightness = cmd.get("brightness", 50)
                contrast = cmd.get("contrast", 50)
                self.video_streamer.set_camera_params(camera_key, brightness, contrast)
                print(f"[WS] set_camera_params: {camera_key} → brightness={brightness}, contrast={contrast}")
            else:
                print("[WS] set_camera_params: video_streamer tidak terhubung")

        # --- GEOFENCE (digambar operator di peta base station) ---
        elif action == "set_geofence":
            if self.geofence is None:
                print("[WS] set_geofence: geofence tidak terpasang di kapal ini")
            else:
                ringkas = self.geofence.configure(
                    enabled=cmd.get("enabled"),
                    lat=cmd.get("lat"),
                    lon=cmd.get("lon"),
                    radius_m=cmd.get("radius_m"),
                )
                # Dikonfirmasi balik supaya panel di peta menampilkan batas yang
                # BENAR-BENAR berlaku di kapal, bukan yang dikira sudah terkirim.
                self._send_warning("info", "GEOFENCE_DIPERBARUI",
                                   f"Geofence diperbarui: {ringkas}")

        # --- LINTASAN ARENA (konvensi sisi) ---
        elif action == "set_track":
            self._terapkan_lintasan(cmd.get("track"))

        # --- GPS OFFSET ---
        elif action == "set_gps_offset":
            lat_offset = float(cmd.get("lat_offset", 0.0))
            lng_offset = float(cmd.get("lng_offset", 0.0))
            self.asv.set_gps_offset(lat_offset, lng_offset)
            print(f"[WS] set_gps_offset: lat={lat_offset:+.7f}, lng={lng_offset:+.7f}")

        # --- THRUSTER TRIM ---
        elif action == "set_thruster_trim":
            port_offset = float(cmd.get("port_offset", 0.0))
            starboard_offset = float(cmd.get("starboard_offset", 0.0))
            self.asv.set_thruster_trim(port_offset, starboard_offset)
            print(f"[WS] set_thruster_trim: port={port_offset:+.3f}, starboard={starboard_offset:+.3f}")

        # --- IMU CALIBRATION ---
        elif action == "start_imu_calibration":
            cal_type = cmd.get("cal_type", "gyro")
            step = int(cmd.get("step", 1))
            self._imu_calibrating = True
            self._imu_cal_step = step
            ok = self.asv.start_imu_calibration(cal_type)
            if ok:
                self._send_ws({
                    "type": "IMU_CALIBRATION_STATUS",
                    "payload": {
                        "step": step,
                        "progress": 5,
                        "message": f"Kalibrasi '{cal_type}' dimulai, menunggu respons FC...",
                        "success": False
                    }
                })
            else:
                self._imu_calibrating = False
                self._send_ws({
                    "type": "IMU_CALIBRATION_STATUS",
                    "payload": {
                        "step": step,
                        "progress": 0,
                        "message": "Gagal: Flight Controller tidak terhubung",
                        "success": False,
                        "error": True
                    }
                })
            print(f"[WS] start_imu_calibration: type={cal_type}, step={step}, ok={ok}")

        elif action == "stop_imu_calibration":
            self._imu_calibrating = False
            print("[WS] IMU calibration stopped by user")

        elif action:
            print(f"[WS] Unknown action: {action}")

    # ------------------------------------------------------------------ #
    #  EMERGENCY STOP                                                      #
    # ------------------------------------------------------------------ #

    # Step yang menghitung sebagai "misi tracking buoy" — harus sama dengan
    # MissionEngine.BUOY_STEP_TYPES.
    _BUOY_STEPS = ("TRACKING_BUOY", "SEQUENTIAL_BUOY", "BUOY_CHASE")

    def _peringatkan_urutan_photo_box(self, steps):
        """
        Beri tahu base station SEKARANG kalau PHOTO_BOX ditaruh tanpa step buoy di
        depannya.

        Tanpa ini, kesalahan urutan hanya terlihat sebagai kapal yang diam 10 detik
        lalu step-nya terlewat — dari base station tidak ada bedanya dengan "fitur
        fotonya rusak". Dikonfirmasi di lapangan: satu sesi tes penuh habis mengejar
        penyebab yang sebenarnya cuma pipeline kurang satu step.
        """
        if not steps:
            return
        buoy_terlihat = False
        for step in steps:
            tipe = str((step or {}).get("type", ""))
            if tipe in self._BUOY_STEPS:
                buoy_terlihat = True
            elif tipe == "PHOTO_BOX" and not buoy_terlihat:
                self._send_warning(
                    level="warning",
                    code="PHOTO_BOX_TANPA_BUOY",
                    message=("Step 'Photo Box' ditaruh sebelum step buoy mana pun. "
                             "Kapal akan menahan posisi 10 detik lalu MELEWATI step "
                             "itu tanpa memotret. Tambahkan Tracking/Sequential Buoy "
                             "atau Buoy Chase sebelum Photo Box."),
                )
                print("[WS] ⚠️ Pipeline misi: PHOTO_BOX tanpa step buoy di depannya — "
                      "step foto akan dilewati.")
                return

    # Lebar kapal (meter) untuk memeriksa kelayakan celah BOX_CHANNEL. Bisa
    # ditimpa per-step lewat field `boat_beam_m`.
    LEBAR_KAPAL_M = 0.40
    # Sisa ruang minimum per sisi antara lambung dan box. Di bawah ini, satu
    # kesalahan kemudi kecil sudah cukup untuk menyenggol.
    CELAH_AMAN_MIN_M = 0.20

    def _peringatkan_celah_box(self, steps):
        """
        Periksa apakah setelan BOX_CHANNEL menyisakan ruang yang masuk akal.

        Jarak lewat diisi dalam METER oleh operator, dan salah ketik satu digit
        (0.3 alih-alih 1.0) tidak kelihatan salah di panel — tapi berarti kapal
        membidik jalur yang lebih sempit dari lambungnya sendiri. Kesalahan seperti
        itu baru ketahuan sebagai suara benturan.

        Diperiksa saat misi DI-LOAD, bukan saat kapal sudah di depan box.
        """
        for step in (steps or []):
            step = step or {}
            if str(step.get("type", "")) != "BOX_CHANNEL":
                continue
            try:
                offset_m = float(step.get("channel_offset_m") or 0)
                lebar_box_m = float(step.get("box_width_m") or 0)
            except (TypeError, ValueError):
                continue
            # Mode meter tidak aktif kalau salah satunya kosong — tidak ada yang
            # bisa diperiksa dalam satuan meter.
            if offset_m <= 0 or lebar_box_m <= 0:
                continue
            try:
                lebar_kapal = float(step.get("boat_beam_m") or self.LEBAR_KAPAL_M)
            except (TypeError, ValueError):
                lebar_kapal = self.LEBAR_KAPAL_M

            sisa = offset_m - (lebar_kapal / 2.0) - (lebar_box_m / 2.0)
            if sisa < self.CELAH_AMAN_MIN_M:
                self._send_warning(
                    level="warning",
                    code="BOX_CHANNEL_TERLALU_SEMPIT",
                    message=(f"Setelan Box Channel menyisakan hanya {sisa*100:.0f} cm "
                             f"antara lambung dan box (jarak lewat {offset_m:.2f} m, "
                             f"lebar kapal {lebar_kapal:.2f} m, lebar box "
                             f"{lebar_box_m:.2f} m). Perbesar 'Jarak Lewat dari Box' "
                             f"atau kapal berisiko menyenggol."),
                )
                print(f"[WS] ⚠️ BOX_CHANNEL: sisa ruang cuma {sisa*100:.0f} cm per sisi.")
                return

    def _execute_emergency_stop(self, reason: str = "unknown"):
        """
        Hentikan kapal SEGERA, lalu kabari base station.

        URUTAN DI BAWAH INI PENTING — jangan dibalik:

          1. ABORT MISI DULU. Ini bagian yang dulu hilang dan membuat seluruh fungsi
             ini praktis tidak berefek: selama misi masih RUNNING, main.py mengirim
             RC override baru ke thruster SETIAP FRAME (~25 Hz) dari
             mission_engine.update_frame(). stop_movement() saja cuma mengirim
             velocity 0 lewat jalur GUIDED, dan frame berikutnya langsung merebut
             throttle kembali sebelum kapal sempat melambat. Begitu status bukan
             RUNNING lagi, main.py pindah ke cabang idle yang menahan kemudi netral.
          2. stop_movement() untuk step yang memang berjalan di GUIDED.
          3. Netralkan RC secara eksplisit, supaya kapal berhenti pada paket ini juga
             dan tidak menunggu frame kamera berikutnya. Sengaja TIDAK diblokir oleh
             gerbang apa pun: perintah ini hanya bisa menghentikan, tidak pernah
             menggerakkan (lihat ASVController.stop_movement).

        CATATAN: kalau operator sedang mengemudikan kapal dari halaman Manual Control
        saat ini dipanggil, perintah joystick berikutnya (dalam <100 ms) akan mengambil
        kemudi kembali. Itu memang disengaja — misinya sudah dibatalkan, dan kapal yang
        sedang dipegang manusia tidak boleh direbut paksa oleh kegagalan sensor.
        """
        try:
            # 1. Batalkan misi yang sedang berjalan — TANPA ini, langkah 2 & 3 di
            #    bawah akan langsung ditimpa oleh frame misi berikutnya.
            if self.mission_engine and self.mission_engine.status == "RUNNING":
                self.mission_engine.abort_mission()
                print(f"[WS] ⛔ Misi di-ABORT oleh emergency stop. Alasan: {reason}")
                self.send_mission_status(self.mission_engine.get_status_dict())

            # 2. Hentikan gerak lewat jalur GUIDED (velocity = 0).
            self.asv.stop_movement()

            # 3. Netralkan kemudi & throttle lewat jalur MANUAL (RC override).
            self.asv.send_manual_rc_drive(0.0, 0.0)

            print(f"[WS] ⛔ EMERGENCY STOP dieksekusi. Alasan: {reason}")

            # 4. Kirim WARNING ke base station agar operator tahu
            self._send_warning(
                level="critical",
                code="EMERGENCY_STOP_EXECUTED",
                message=f"⛔ EMERGENCY STOP dieksekusi di kapal! Alasan: {reason}. "
                        f"Misi dibatalkan dan semua thruster dimatikan."
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
    #  STATUSTEXT CALLBACK (IMU Calibration Progress)                     #
    # ------------------------------------------------------------------ #

    def _on_statustext(self, text: str):
        """
        Dipanggil oleh ASVState setiap ada STATUSTEXT baru dari Pixhawk.
        Saat kalibrasi IMU aktif, forward progress ke base station.
        """
        if not self._imu_calibrating:
            return

        text_lower = text.lower()
        cal_keywords = ["cal", "calibrat", "accel", "gyro", "compass", "mag", "level"]
        if not any(kw in text_lower for kw in cal_keywords):
            return

        is_complete = any(kw in text_lower for kw in ["complete", "compl", "done", "success", "passed"])
        is_failed = any(kw in text_lower for kw in ["fail", "error", "abort", "timeout"])

        progress = 100 if is_complete else (0 if is_failed else 60)

        self._send_ws({
            "type": "IMU_CALIBRATION_STATUS",
            "payload": {
                "step": self._imu_cal_step,
                "progress": progress,
                "message": text,
                "success": is_complete,
                "failed": is_failed
            }
        })

        if is_complete or is_failed:
            self._imu_calibrating = False

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

    def _handle_set_manual_source(self, raw_source):
        """
        Pindahkan sumber kendali manual antara mini PC dan remote RC fisik.

        URUTAN saat menyerahkan ke remote (jangan diubah):
          1. Abort misi — dilakukan SEBELUM gerbang blokir dipasang, karena
             abort_mission() memanggil stop_movement() yang butuh jalur perintah masih
             terbuka untuk menghentikan kapal dengan rapi.
          2. Paksa mode MANUAL — step misi bisa saja meninggalkan kapal di GUIDED, dan
             di GUIDED stik remote tidak menggerakkan apa pun.
          3. Baru pindahkan sumber kendali (memasang gerbang + melepas override RC).
        """
        target = manual_source.normalize(raw_source)
        if target is None:
            print(f"[WS] set_manual_source: sumber '{raw_source}' tidak dikenal "
                  f"(pilih 'minipc' atau 'remote')")
            self._send_manual_source_ack(ok=False, requested=raw_source)
            return

        if target == manual_source.REMOTE:
            if self.mission_engine and self.mission_engine.status == "RUNNING":
                self.mission_engine.abort_mission()
                print("[WS] 🎮 Misi di-ABORT karena kendali diserahkan ke remote RC.")
                self.send_mission_status(self.mission_engine.get_status_dict())
            self.asv.set_mode("MANUAL")

        ok = self.asv.set_manual_source(target)
        self._send_manual_source_ack(ok=ok, requested=target)

    def notify_manual_source(self):
        """
        Kabarkan sumber kendali yang aktif SEKARANG ke base station.

        Publik — dipakai RCSourceSwitch saat switch fisik di remote memindahkan
        kendali. Tanpa ini, panel di dashboard tetap menampilkan sumber yang lama
        sampai telemetri berikutnya menyusul, dan operator tidak tahu perpindahan
        yang baru saja dia lakukan sudah benar-benar terjadi.
        """
        self._send_manual_source_ack(ok=True, requested=None)

    def send_warning(self, level: str, code: str, message: str):
        """Kirim WARNING ke base station. Publik — dipakai modul di luar kelas ini."""
        self._send_warning(level, code, message)

    def _send_manual_source_ack(self, ok: bool, requested):
        """Beri tahu base station sumber kendali yang BENAR-BENAR aktif setelah perintah."""
        self._send_ws({
            "type": "MANUAL_SOURCE",
            "payload": {
                "source": self.asv.get_manual_source(),
                "requested": requested,
                "ok": bool(ok),
            }
        })

    def _terapkan_lintasan(self, nama):
        """
        Ganti lintasan arena (konvensi sisi merah/hijau & box) secara live.

        DITOLAK SELAGI MISI BERJALAN — ini keputusan keselamatan, bukan kelalaian.
        Konvensi sisi menentukan ke arah mana kapal membanting saat hanya satu
        penanda terlihat. Membaliknya di tengah misi membalik SEKETIKA setiap
        koreksi kemudi yang sedang berjalan: manuver yang tadinya menjauhi bola
        berubah jadi menuju bola, pada jarak yang sudah dekat. Operator cukup
        menghentikan misi lebih dulu — beberapa detik, dibanding satu tabrakan.

        Balasannya SELALU berisi lintasan yang BENAR-BENAR aktif di kapal, bukan
        yang diminta, supaya dashboard tidak pernah menampilkan setelan yang
        sebenarnya ditolak.
        """
        diminta = str(nama or "").strip().upper()
        aktif = gate_convention.lintasan_aktif()

        if diminta not in gate_convention.daftar_lintasan():
            print(f"[WS] set_track: lintasan '{nama}' tidak dikenal, diabaikan")
            self._kirim_ack_lintasan(ok=False,
                                     alasan=f"Lintasan '{nama}' tidak dikenal")
            return

        misi_jalan = (self.mission_engine is not None
                      and self.mission_engine.status == "RUNNING")
        if misi_jalan and diminta != aktif:
            print(f"[WS] ⛔ set_track {diminta} DITOLAK — misi sedang berjalan.")
            self._kirim_ack_lintasan(
                ok=False,
                alasan="Misi sedang berjalan. Hentikan misi dulu — membalik "
                       "konvensi sisi di tengah misi membalik arah setiap "
                       "koreksi kemudi seketika.")
            return

        berubah = gate_convention.set_lintasan(diminta)
        sisi = gate_convention.sisi_lintasan(diminta)
        if berubah:
            print(f"[WS] 🔀 Lintasan → {diminta} | " + "  ".join(
                f"{k}={v}" for k, v in sisi.items()))
            self._send_warning("info", "LINTASAN_DIPERBARUI",
                               f"Lintasan arena diubah ke {diminta}.")
        self._kirim_ack_lintasan(ok=True)

    def _kirim_ack_lintasan(self, ok: bool, alasan: str = ""):
        """Balas dengan lintasan yang benar-benar berlaku di kapal saat ini."""
        aktif = gate_convention.lintasan_aktif()
        self._send_ws({
            "type": "TRACK_CONFIG",
            "payload": {
                "track": aktif,
                "ok": bool(ok),
                "reason": alasan,
                "sides": gate_convention.sisi_lintasan(aktif),
            },
        })

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
                t = self.asv.get_telemetry_dict_with_offset()
                try:
                    payload = {
                        "lat": t.get("lat"),
                        "lng": t.get("lon"),
                        "heading": t.get("heading"),
                        # COG = arah gerak sesungguhnya (dari vektor kecepatan GPS),
                        # beda dari heading yang menunjukkan arah haluan menghadap.
                        # cog_valid=False berarti kapal terlalu pelan → angka basi.
                        "cog": t.get("cog"),
                        "cog_valid": t.get("cog_valid", False),
                        "sog": t.get("ground_speed"),
                        "pitch": t.get("pitch"),
                        "roll": t.get("roll"),
                        "yaw": t.get("yaw"),
                        "battery_pct": t.get("battery_remaining"),
                        "battery_volt": t.get("battery_voltage"),
                        "satellites": t.get("satellites_visible", 0),
                        # Jenis fix SUNGGUHAN dari GPS_RAW_INT (0/1 tanpa fix, 2=2D,
                        # 3=3D, 4+=DGPS/RTK). Sebelumnya dikarang `3 if lat else 0`,
                        # yang melaporkan "3D fix" bahkan selagi penerima masih
                        # mencari satelit — koordinat pertama saat akuisisi memang
                        # bukan nol, cuma meleset puluhan meter. Perekam jejak yang
                        # mempercayai angka itu menggambar lompatan melintasi danau
                        # sebagai lintasan yang sungguh ditempuh.
                        "gps_fix": t.get("gps_fix_type", 0),
                        "gps_hdop": t.get("gps_eph", 0.0),
                        "is_armed": t.get("is_armed", False),
                        "mode": t.get("mode", "UNKNOWN"),
                        "is_connected": t.get("is_connected", False),
                        "camera_connected": self.video_streamer.is_camera_ok() if self.video_streamer else False,
                        "is_recording": self.video_streamer.is_recording if self.video_streamer else False,
                        "recording_filename": self.video_streamer.recording_filename if (self.video_streamer and self.video_streamer.is_recording) else "",
                        "recording_resolution": f"{self.video_streamer.record_width}x{self.video_streamer.record_height}" if (self.video_streamer and self.video_streamer.is_recording) else "",
                        # Streaming toggle state — base station bisa sync tombol ON/OFF
                        "is_streaming": self.video_streamer.is_streaming if self.video_streamer else False,
                        # Sumber kendali manual aktif: "minipc" | "remote"
                        "manual_source": self.asv.get_manual_source(),
                        # Apakah sumber kendali sedang ditentukan switch fisik di
                        # remote. Saat true, tombol di dashboard hanya indikator.
                        "rc_source_switch": bool(
                            self.rc_source_switch and self.rc_source_switch.enabled),
                        "rc_source_channel": (
                            self.rc_source_switch.channel if self.rc_source_switch else 0),
                        # Batas yang BENAR-BENAR berlaku di kapal — peta menggambar
                        # dari sini, bukan dari yang tersimpan di DB, supaya
                        # lingkaran di layar selalu mewakili keadaan sebenarnya.
                        # Lintasan arena yang BENAR-BENAR berlaku di kapal. Ikut di
                        # telemetri, bukan cuma di ACK, supaya dashboard yang baru
                        # dibuka (atau baru tersambung ulang) langsung menampilkan
                        # keadaan sebenarnya tanpa perlu bertanya.
                        "track": gate_convention.lintasan_aktif(),
                        "geofence_enabled": bool(self.geofence and self.geofence.enabled),
                        "geofence_radius_m": (self.geofence.radius_m if self.geofence else 0),
                        "geofence_lat": (self.geofence.center[0]
                                         if self.geofence and self.geofence.center else 0),
                        "geofence_lon": (self.geofence.center[1]
                                         if self.geofence and self.geofence.center else 0),
                    }

                    self.ws.send(json.dumps({
                        "type": "TELEMETRY",
                        "payload": payload
                    }))
                except Exception as e:
                    print(f"[WS] Send error: {e}")
            time.sleep(0.1)  # Kirim setiap 100ms
