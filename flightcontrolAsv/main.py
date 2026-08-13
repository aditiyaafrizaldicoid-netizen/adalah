import sys
import os

sys.dont_write_bytecode = True  # Mencegah Python membuat file cache __pycache__ / .pyc
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from dotenv import load_dotenv
load_dotenv()  # Baca .env sebelum os.getenv() digunakan

import time
import threading

from core.client import ASVController
from connection.websocket import ASVWebSocketClient
from camera.streamer import VideoStreamer


def main():
    print("==================================================")
    print(" 🚢 ASV FLIGHT CONTROLLER + WEBSOCKET CLIENT ")
    print("==================================================")

    port = os.getenv("ASV_TEST_PORT", "/dev/ttyACM0")
    baudrate = 115200

    asv = ASVController(port=port, baudrate=baudrate)
    asv.start()

    print("[Main] Menunggu koneksi Pixhawk...")
    while not asv.is_connected():
        time.sleep(0.5)

    # ------------------------------------------------------------------ #
    #  Inisialisasi YOLO Tracker, Tracking Controller & Speed Scheduler  #
    # ------------------------------------------------------------------ #
    from vision.tracker import BallTracker
    from control.pid_tracker import TrackingController
    from control.speed_scheduler import SpeedScheduler
    from control.mission_engine import MissionEngine

    camera_width = 640

    model_path = os.path.join(os.path.dirname(__file__), "models", "best.pt")
    tracker = BallTracker(
        model_path=model_path,
        target_class=[0, 1],
        conf_threshold=0.6
    )

    controller = TrackingController(
        frame_width=camera_width,
        kp=0.051,
        ki=0.0,
        kd=0.0,
        max_turn_rate=40.0
    )

    speed_scheduler = SpeedScheduler(max_base_throttle=0.4)

    # Inisialisasi Mission Engine dengan SpeedScheduler
    mission_engine = MissionEngine(
        asv=asv,
        tracker=tracker,
        tracking_controller=controller,
        speed_scheduler=speed_scheduler
    )

    ws_url = os.getenv("ASV_WS_URL", "ws://localhost:3000/api/v1/ws/asv")
    ws_client = ASVWebSocketClient(asv, ws_url=ws_url)

    ws_client.set_tracking_controller(controller)
    ws_client.set_speed_scheduler(speed_scheduler)
    ws_client.set_mission_engine(mission_engine)

    # Callback: kirim status misi ke Base Station via WebSocket setiap kali berubah
    def on_mission_status_change(status_dict):
        ws_client.send_mission_status(status_dict)

    mission_engine.set_status_callback(on_mission_status_change)

    ws_client.start()

    # ------------------------------------------------------------------ #
    #  Inisialisasi Telemetry Blackbox Logger                              #
    # ------------------------------------------------------------------ #
    from core.logger import TelemetryLogger
    logger = TelemetryLogger()

    # ------------------------------------------------------------------ #
    #  Frame processing callback (dipanggil ~30 FPS oleh VideoStreamer)   #
    # ------------------------------------------------------------------ #
    import time as _time
    # Throttle log messages berulang agar tidak spam terminal (max 1x per interval)
    _log_throttle: dict = {}  # key -> last_print_time
    _LOG_INTERVAL = 5.0        # detik: interval print pesan berulang

    def _throttled_print(key: str, message: str, interval: float = _LOG_INTERVAL):
        """Print message maksimum satu kali per interval detik untuk key tertentu."""
        now = _time.time()
        if now - _log_throttle.get(key, 0.0) >= interval:
            print(message)
            _log_throttle[key] = now

    def process_and_control(frame):
        # Ambil gate FSM state dari mission_engine untuk ditampilkan di OSD tracker
        gate_fsm_state = getattr(mission_engine, '_gate_state', None) if mission_engine.status == "RUNNING" else None

        # Deteksi bola dan hitung midpoint gate; sertakan state untuk OSD jika ada
        state_name = getattr(controller, "state", None)
        processed_frame, gate_x, gate_y, left_visible, right_visible = tracker.process_frame(
            frame,
            state_label=state_name,
            gate_state=gate_fsm_state
        )

        if not asv.is_connected():
            return processed_frame

        telemetry = asv.get_telemetry()
        mode = telemetry.mode
        state = "IDLE"

        if mission_engine.status == "RUNNING":
            # ----------------------------------------------------------------
            # MISSION ENGINE RUNNING (Mode MANUAL RC Override):
            # update_frame() mengembalikan steer_norm (-1..+1) dan thr_norm (0..1)
            # Perintah RC override dikirim ke Pixhawk jika sudah ARM & mode MANUAL.
            # ----------------------------------------------------------------
            steer_norm, thr_norm, step_label = mission_engine.update_frame(
                frame, gate_x, left_visible, right_visible
            )
            state = step_label

            if telemetry.is_armed and mode == "MANUAL":
                asv.send_manual_rc_drive(steer_norm, thr_norm)
            elif not telemetry.is_armed:
                _throttled_print("mission_disarmed",
                    f"[MISSION] ⚠️ DISARMED — step '{step_label}' berjalan, gerakan ditahan.")
        else:
            # ---- Mission IDLE / PAUSED / FINISHED ----
            state = "IDLE"
            # if telemetry.is_armed and mode == "MANUAL":
            #     if gate_x is not None:
            #         # Live tracking test di mode MANUAL saat ARM
            #         # Throttle langsung dari max_base_throttle — FC internal yang mengontrol PID throttle
            #         steer_norm = controller.compute_normalized_steering(gate_x)
            #         asv.send_manual_rc_drive(steer_norm, speed_scheduler.max_base_throttle)
            #     else:
            asv.send_manual_rc_drive(0.0, 0.0)  # Stop motor & netralkan kemudi

        # Catat log blackbox
        error_px = gate_x - camera_width // 2 if gate_x is not None else None
        logger.log_record(asv.get_telemetry_dict(), state=state, gate_x=gate_x, error_px=error_px)

        return processed_frame

    # ------------------------------------------------------------------ #
    #  Setup Video Streamer (Pushing ke Backend)                          #
    # ------------------------------------------------------------------ #
    video_upload_url = os.getenv("ASV_VIDEO_URL", "http://localhost:3000/api/v1/video/upload")
    flip_cam = os.getenv("ASV_CAM_FLIP", "0").lower() in ("1", "true", "yes")

    video_streamer = VideoStreamer(
        camera_index=0,
        width=camera_width,
        height=480,
        fps=5,  # Dikurangi dari 30 ke 5 agar tidak DDoS backend Next.js
        backend_url=video_upload_url,
        frame_callback=process_and_control,
        flip_horizontal=True
    )
    ws_client.set_video_streamer(video_streamer)
    video_streamer.start()

    try:
        print("\n[Main] Sistem berjalan. Tekan Ctrl+C untuk berhenti.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Main] Dibatalkan oleh pengguna.")
    finally:
        video_streamer.stop()
        ws_client.stop()
        asv.stop()
        print("\n[Main] Selesai. Semua koneksi ditutup.")
        os._exit(0)  # Force exit untuk membunuh thread yang hang (jika ada)

if __name__ == "__main__":
    main()
