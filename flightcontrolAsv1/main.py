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
    #  Kalibrasi Hardware: Kompensasi wiring motor & arah servo           #
    # ------------------------------------------------------------------ #
    # Motor thruster terwiring terbalik secara fisik (SERVO1 → motor kanan, bukan kiri),
    # sehingga steering signal dinegasi di ManualRCController agar thruster benar arahnya.
    # Akibatnya, SERVO3/SERVO4 (GroundSteering) juga ikut terbalik — dikoreksi di sini
    # dengan SERVO_REVERSED=1 agar output servo dibalik kembali ke arah yang benar.
    print("[Main] Mengatur kalibrasi servo ArduPilot (SERVO3_REVERSED & SERVO4_REVERSED)...")
    asv.set_param("SERVO3_REVERSED", 1)
    asv.set_param("SERVO4_REVERSED", 1)
    time.sleep(0.3)  # Beri waktu ArduPilot memproses parameter sebelum misi dimulai

    # ------------------------------------------------------------------ #
    #  Inisialisasi YOLO Tracker, Tracking Controller & Speed Scheduler  #
    # ------------------------------------------------------------------ #
    from vision.tracker import BallTracker
    from control.pid_tracker import TrackingController
    from control.speed_scheduler import SpeedScheduler
    from control.mission_engine import MissionEngine

    # Logitech MX Brio @ 1920x1080 (Full HD)
    camera_width = 1920
    camera_height = 1080

    model_path = os.path.join(os.path.dirname(__file__), "models", "best.pt")
    tracker = BallTracker(
        model_path=model_path,
        target_class=[0, 1],
        conf_threshold=0.2
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

    # State OSD: gunakan label frame sebelumnya karena update_frame dipanggil SETELAH
    # tracker.process_frame(). TrackingController tidak punya atribut 'state'.
    _osd: dict = {"last_label": None}

    def process_and_control(frame):
        # Ambil gate_state dari mission_engine untuk OSD (agar tracker bisa menampilkan label)
        state_name  = _osd["last_label"]   # label dari frame sebelumnya (1-frame lag OK)
        gate_state  = mission_engine.gate_lock_state if mission_engine.status == "RUNNING" else None

        # Deteksi bola, hitung midpoint fallback, dan dapatkan detected_balls per class
        # tracker.process_frame() mengembalikan 4 nilai:
        #   processed_frame : frame dengan anotasi
        #   gate_x, gate_y  : midpoint fallback (digunakan saat SEARCHING)
        #   detected_balls  : {"red": [...], "green": [...]} — digunakan Gate State Machine
        processed_frame, gate_x, gate_y, detected_balls = tracker.process_frame(
            frame,
            state_label=state_name,
            gate_state=gate_state
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
            # detected_balls diteruskan ke Gate State Machine di MissionEngine.
            # PENTING: RC override dikirim selama ARM — tidak menunggu konfirmasi
            # mode == "MANUAL" dari telemetry karena mode switch butuh beberapa frame
            # untuk terkonfirmasi balik, dan setiap frame yang terlewat = koreksi hilang.
            # ----------------------------------------------------------------
            steer_norm, thr_norm, step_label = mission_engine.update_frame(
                frame, gate_x, detected_balls=detected_balls
            )
            state = step_label
            _osd["last_label"] = step_label  # simpan untuk OSD frame berikutnya

            if telemetry.is_armed:
                # Kirim RC override hanya untuk step MANUAL mode (steer/thr non-zero)
                # atau saat mode MANUAL (termasuk fase transisi GUIDED→MANUAL).
                # Untuk step GUIDED (CUSTOM_FORWARD, PRECISION_TURN, HOLD, dll.),
                # gerakan dikontrol oleh send_velocity() — RC override tidak dikirim agar
                # tidak menginterferensi command velocity (terutama jika GUIDED_OPTIONS=1).
                needs_rc = (mode == "MANUAL") or (steer_norm != 0.0 or thr_norm != 0.0)
                if needs_rc:
                    asv.send_manual_rc_drive(steer_norm, thr_norm)
            else:
                _throttled_print("mission_disarmed",
                    f"[MISSION] ⚠️ DISARMED — step '{step_label}' berjalan, gerakan ditahan.")
        else:
            # ---- Mission IDLE / PAUSED / FINISHED ----
            state = "IDLE"
            _osd["last_label"] = None
            # Netralkan kemudi & hentikan motor saat tidak ada mission aktif
            asv.send_manual_rc_drive(0.0, 0.0)

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
        height=camera_height,
        fps=15,  # Ditingkatkan ke 15 FPS agar pergerakan video lebih halus
        backend_url=video_upload_url,
        frame_callback=process_and_control,
        flip_horizontal=flip_cam
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
