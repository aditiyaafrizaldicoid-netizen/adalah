import os
import time
from client import ASVController
from ws_client import ASVWebSocketClient
from video_stream import VideoStreamer

def main():
    print("==================================================")
    print(" 🚢 ASV FLIGHT CONTROLLER + WEBSOCKET CLIENT ")
    print("==================================================")

    # Ganti dengan port yang sesuai di Mini PC
    # Jika menggunakan simulasi SITL (misalnya ArduRover SITL): port = "tcp:127.0.0.1:5760"
    port = os.getenv("ASV_TEST_PORT", "/dev/ttyACM0")
    baudrate = 9600

    asv = ASVController(port=port, baudrate=baudrate)
    asv.start()

    # Tunggu sampai Pixhawk benar-benar terkoneksi (menerima heartbeat)
    print("[Main] Menunggu koneksi Pixhawk...")
    while not asv.is_connected():
        time.sleep(0.5)

    # Otomatis reset Pixhawk ke Mode RC Fisik (Throttle & Steering) saat script dijalankan
    print("[Main] Mengembalikan konfigurasi Pixhawk ke Mode RC Fisik (Default)...")
    asv.apply_rc_mode()

    ws_url = os.getenv("ASV_WS_URL", "ws://bodrex-Legion-5-16IRX9.local:3000/api/v1/ws/asv")
    ws_client = ASVWebSocketClient(asv, ws_url=ws_url)
    ws_client.start()

    # ------------------------------------------------------------------ #
    #  Inisialisasi YOLO Tracker dan Tracking Controller                   #
    # ------------------------------------------------------------------ #
    from vision.tracker import BallTracker
    from control.pid_tracker import TrackingController

    camera_width = 640

    # Tracker: deteksi bola hijau (class 0) dan bola merah (class 1) sebagai gate
    tracker = BallTracker(
        model_path="best.pt",
        target_class=[0, 1],
        conf_threshold=0.6
    )

    # Controller: gunakan GUIDED mode dengan forward_speed dan turn_rate
    controller = TrackingController(
        frame_width=camera_width,
        kp=0.04,
        ki=0.001,
        kd=0.008,
        forward_speed=1.0,          # m/s kecepatan maju saat approaching/passing
        align_threshold_px=40,      # toleransi piksel untuk dianggap lurus
        pass_duration=2.5,          # detik maju lurus saat melewati gate
        cooldown_duration=3.0       # detik cooldown setelah lewat gate
    )

    def process_and_control(frame):
        # Deteksi bola dan hitung midpoint gate; sertakan state untuk OSD
        processed_frame, gate_x, gate_y = tracker.process_frame(
            frame,
            state_label=controller.state
        )

        if not asv.is_connected():
            return processed_frame

        telemetry = asv.get_telemetry()
        mode = telemetry.mode

        if mode == "MANUAL":
            # Mode MANUAL: Sepenuhnya dikendalikan Remote RC fisik
            # Lepaskan semua override agar RC bekerja 100% tanpa gangguan Python
            asv.release_rc()

        elif mode == "GUIDED":
            # ---- Mode GUIDED: Gunakan NavigationControl.send_velocity() ----
            # Controller menghitung forward speed (m/s) dan turn rate (deg/s)
            forward_speed, turn_rate_deg, state = controller.compute_velocity(gate_x)

            if state in (controller.STATE_ALIGNING,
                         controller.STATE_APPROACHING,
                         controller.STATE_PASSING):
                # Kirim perintah velocity MAVLink ke Pixhawk
                asv.move_forward(forward_speed) if turn_rate_deg == 0.0 else asv.turn(forward_speed, turn_rate_deg)
            else:
                # SEARCHING atau COOLDOWN: hentikan kapal
                asv.stop_movement()

        else:
            # Mode lain (AUTO, LOITER, dll): biarkan autopilot yang handle
            pass

        return processed_frame

    # ------------------------------------------------------------------ #
    #  Setup Video Streamer (Pushing ke Backend)                          #
    # ------------------------------------------------------------------ #
    video_upload_url = os.getenv("ASV_VIDEO_URL", "http://bodrex-Legion-5-16IRX9.local:3000/api/v1/video/upload")
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
