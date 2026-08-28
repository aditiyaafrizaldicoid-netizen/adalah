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


def _fetch_camera_resolution(default_width: int, default_height: int):
    """
    Fetch camera_width/camera_height dari /api/v1/pid-config di awal startup —
    SEBELUM tracker/controller/mission_engine/video_streamer dibuat, karena resolusi
    capture kamera fisik tidak bisa diganti live setelah cv2.VideoCapture ter-init.

    Selalu kembalikan sepasang int yang valid — fallback ke default_width/height
    kalau backend belum siap, field belum diisi di DB, atau nilainya tidak masuk
    akal (<=0), supaya boot tidak pernah gagal gara-gara config resolusi.
    """
    import urllib.request
    import json
    try:
        url = "http://localhost:3000/api/v1/pid-config"
        req = urllib.request.Request(url, headers={"User-Agent": "ASVFlightController"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "success" and data.get("data"):
                    cfg = data["data"]
                    w = int(cfg.get("camera_width") or 0)
                    h = int(cfg.get("camera_height") or 0)
                    if w > 0 and h > 0:
                        print(f"[Main] 📥 Resolusi kamera dari DB: {w}x{h}")
                        return w, h
    except Exception as e:
        print(f"[Main] Warning: Could not fetch camera resolution from DB ({e})")

    print(f"[Main] Menggunakan resolusi kamera default: {default_width}x{default_height}")
    return default_width, default_height


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

    # Resolusi kamera live-tunable dari Calibration → Vision/Camera di base station
    # (disimpan di DB via /api/v1/pid-config, field camera_width/camera_height).
    # HARUS diambil SEBELUM tracker/controller/mission_engine/video_streamer dibuat —
    # beda dari PID gain dkk. yang bisa di-update live setelah objek dibuat, resolusi
    # capture kamera fisik (cv2.VideoCapture) tidak bisa diganti setelah kamera
    # ter-inisialisasi tanpa re-init hardware penuh. Fallback ke 1920x1080 (Logitech
    # MX Brio) kalau fetch gagal (mis. backend belum siap) — resolusi REFERENSI
    # tempat semua threshold piksel MissionEngine dikalibrasi (lihat
    # MissionEngine.REFERENCE_FRAME_WIDTH/HEIGHT & _apply_resolution_scaling()).
    camera_width, camera_height = _fetch_camera_resolution(default_width=1920, default_height=1080)

    model_path = os.path.join(os.path.dirname(__file__), "models", "best.pt")
    tracker = BallTracker(
        model_path=model_path,
        target_class=[0, 1],
        conf_threshold=0.45
    )

    controller = TrackingController(
        frame_width=camera_width,
        kp=0.051,
        ki=0.0,
        kd=0.0,
        max_turn_rate=40.0
    )

    speed_scheduler = SpeedScheduler(max_base_throttle=0.4)

    # Inisialisasi Mission Engine dengan SpeedScheduler — camera_width/height dipakai
    # untuk menskalakan otomatis SEMUA threshold berbasis piksel (lihat
    # MissionEngine._apply_resolution_scaling()), TIDAK perlu edit konstanta manual
    # tiap kali resolusi kamera diganti.
    mission_engine = MissionEngine(
        asv=asv,
        tracker=tracker,
        tracking_controller=controller,
        speed_scheduler=speed_scheduler,
        camera_width=camera_width,
        camera_height=camera_height
    )

    ws_url = os.getenv("ASV_WS_URL", "ws://localhost:3000/api/v1/ws/asv")
    ws_client = ASVWebSocketClient(asv, ws_url=ws_url)

    # set_tracker() SEBELUM set_tracking_controller(): set_tracking_controller() memicu
    # fetch_and_apply_pid_config() (fetch sekali dari DB), yang butuh self.tracker sudah
    # ter-set agar min_detection_area_px2 ikut ter-apply pada fetch pertama itu juga.
    ws_client.set_tracker(tracker)
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
        # ---- Foto misi ber-geo-tag (step TAKE_IMAGE) ----
        # HARUS di sini, PALING AWAL: tracker.process_frame() di bawah menggambar
        # bounding box & OSD ke frame secara IN-PLACE, sehingga setelah dipanggil
        # pemandangan aslinya tidak bisa didapat lagi. Foto yang dinilai juri harus
        # berisi pemandangan asli, bukan anotasi debug.
        # MissionEngine hanya menentukan KAPAN memotret; frame bersihnya dari sini.
        if mission_engine.status == "RUNNING" and mission_engine.capture_pending:
            mission_engine.capture_now(frame)

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
            #
            # try/except DI SINI WAJIB ADA: kalau update_frame() melempar exception
            # (mis. field mission JSON yang malformed lolos dari safe-parsing di
            # mission_engine.py), kapal HARUS berhenti (RC netral), BUKAN terus
            # jalan dengan RC command TERAKHIR yang pernah terkirim (karena tidak
            # ada override baru yang dikirim frame ini) sampai exception ini
            # membunuh thread streaming/kontrol sepenuhnya (lihat try/except di
            # camera/streamer.py _upload_loop — itu lapis pertahanan LUAR yang
            # mencegah thread mati total, tapi TIDAK otomatis menghentikan kapal;
            # try/except di sini yang bertanggung jawab atas itu).
            # ----------------------------------------------------------------
            try:
                steer_norm, thr_norm, step_label = mission_engine.update_frame(
                    frame, gate_x, detected_balls=detected_balls
                )
            except Exception as e:
                print(f"[MISSION] ⚠️ update_frame() error — RC dinetralkan demi keamanan: {e}")
                import traceback
                traceback.print_exc()
                asv.send_manual_rc_drive(0.0, 0.0)
                state = "MISSION_ERROR"
                _osd["last_label"] = state
                error_px = gate_x - camera_width // 2 if gate_x is not None else None
                logger.log_record(asv.get_telemetry_dict(), state=state, gate_x=gate_x, error_px=error_px)
                return processed_frame

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
