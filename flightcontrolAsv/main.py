import sys
import os

sys.dont_write_bytecode = True  # Mencegah Python membuat file cache __pycache__ / .pyc
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
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
    baudrate = 9600

    asv = ASVController(port=port, baudrate=baudrate)
    asv.start()

    print("[Main] Menunggu koneksi Pixhawk...")
    while not asv.is_connected():
        time.sleep(0.5)

    # ------------------------------------------------------------------ #
    #  Inisialisasi YOLO Tracker dan Tracking Controller                  #
    # ------------------------------------------------------------------ #
    from vision.tracker import BallTracker
    from control.pid_tracker import TrackingController
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
        kp=0.04,
        ki=0.001,
        kd=0.008,
        forward_speed=0.4,
        max_turn_rate=15.0,
        align_threshold_px=40.0,
        pass_duration=2.5,
        cooldown_duration=3.0
    )

    # Inisialisasi Mission Engine
    mission_engine = MissionEngine(asv=asv, tracker=tracker, tracking_controller=controller)

    ws_url = os.getenv("ASV_WS_URL", "ws://localhost:3000/api/v1/ws/asv")
    ws_client = ASVWebSocketClient(asv, ws_url=ws_url)

    ws_client.set_tracking_controller(controller)
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
    _GUIDED_KEEPALIVE_INTERVAL = 1.0   # detik: interval kirim keepalive velocity=0
    _LOG_INTERVAL = 5.0                # detik: interval print pesan berulang
    _guided_keepalive_time = [0.0]

    def _throttled_print(key: str, message: str, interval: float = _LOG_INTERVAL):
        """Print message maksimum satu kali per interval detik untuk key tertentu."""
        now = _time.time()
        if now - _log_throttle.get(key, 0.0) >= interval:
            print(message)
            _log_throttle[key] = now

    def process_and_control(frame):
        # Deteksi bola dan hitung midpoint gate; sertakan state untuk OSD jika ada
        state_name = getattr(controller, "state", None)
        processed_frame, gate_x, gate_y = tracker.process_frame(
            frame,
            state_label=state_name
        )

        if not asv.is_connected():
            return processed_frame

        telemetry = asv.get_telemetry()
        mode = telemetry.mode

        if mode == "MANUAL":
            # Mode MANUAL: Sepenuhnya dikendalikan Remote RC fisik
            pass

        elif mode == "GUIDED":
            state = getattr(controller, "state", "GUIDED")

            if mission_engine.status == "RUNNING":
                # ----------------------------------------------------------------
                # MISSION ENGINE RUNNING:
                # update_frame() SELALU dipanggil agar timer step (warmup, hold,
                # take_image) terus berjalan walaupun kapal belum di-ARM.
                # Perintah velocity baru dikirim ke MAVLink jika sudah ARM.
                # ----------------------------------------------------------------
                forward_speed, turn_rate_deg, step_label = mission_engine.update_frame(frame, gate_x)
                state = step_label

                if telemetry.is_armed:
                    # Kirim perintah gerakan hanya jika kapal sudah di-ARM
                    if forward_speed != 0.0 or turn_rate_deg != 0.0:
                        if turn_rate_deg == 0.0:
                            asv.move_forward(forward_speed)
                        else:
                            asv.turn(forward_speed, turn_rate_deg)
                else:
                    # Belum ARM → timer step tetap jalan, tapi servo diam
                    # (print di-throttle agar tidak spam tiap frame)
                    _throttled_print("mission_disarmed",
                        f"[MISSION] ⚠️ DISARMED — step '{step_label}' berjalan, gerakan ditahan.")

            else:
                # ---- Mission IDLE / PAUSED / FINISHED: JANGAN gerak otomatis! ----
                state = "IDLE"
                if telemetry.is_armed:
                    # Kirim velocity=0 keepalive setiap 1 detik agar ArduRover
                    # tidak timeout (GUID_TIMEOUT) dan auto-switch ke HOLD
                    now = _time.time()
                    if now - _guided_keepalive_time[0] >= _GUIDED_KEEPALIVE_INTERVAL:
                        asv.stop_movement(silent=True)  # silent → tidak print log
                        _guided_keepalive_time[0] = now
                else:
                    _throttled_print("guided_disarmed",
                        "[GUIDED] ⚠️ Kapal DISARMED. Tekan ARM di Base Station agar siap misi.")



            # Catat log blackbox
            error_px = gate_x - camera_width // 2 if gate_x is not None else None
            logger.log_record(asv.get_telemetry_dict(), state=state, gate_x=gate_x, error_px=error_px)




        else:
            # Mode lain (AUTO, LOITER, dll): biarkan autopilot yang handle
            pass

        return processed_frame

    # ------------------------------------------------------------------ #
    #  Setup Video Streamer (Pushing ke Backend)                          #
    # ------------------------------------------------------------------ #
    video_upload_url = os.getenv("ASV_VIDEO_URL", "http://localhost:3000/api/v1/video/upload")
    video_streamer = VideoStreamer(
        camera_index=0,
        width=camera_width,
        height=640,
        fps=30,
        backend_url=video_upload_url,
        frame_callback=process_and_control
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

if __name__ == "__main__":
    main()
