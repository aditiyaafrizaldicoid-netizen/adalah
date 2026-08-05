#!/usr/bin/env python3
"""
=============================================================================
 🚢 INTERACTIVE OBJECT DETECTION + VISUAL PID TRACKING TEST UI
=============================================================================
 Script Interaktif Terminal untuk menguji integrasi Kamera RGB + YOLO Detection
 + Visual PID Control secara real-time langsung ke Pixhawk (Mode GUIDED).

 Fitur:
 - Deteksi Buoy Merah 🔴 & Hijau 🟢 (YOLO) & Hitung Gate Center X
 - Kalkulasi Visual PID (Pixel Error -> Turn Rate deg/s & Forward Speed m/s)
 - Live Tuning Kp, Ki, Kd, dan Kecepatan dari Keyboard
 - Visualisasi Real-Time di Terminal Terminal UI
=============================================================================
"""

import sys
sys.dont_write_bytecode = True

import os
import time
import signal
import threading

import cv2
from core.client import ASVController
from vision.tracker import BallTracker
from control.pid_tracker import TrackingController

# State Program
running = True
auto_tracking_active = False

# Controller Settings Default
target_speed = 0.2    # m/s
kp_val = 1.0
ki_val = 0.01
kd_val = 0.01
max_turn_val = 60.0      # deg/s

def signal_handler(sig, frame):
    global running
    print("\n[UI] ⚠️ Menutup program tracking interaktif...")
    running = False

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def render_ui(asv: ASVController, last_detection: dict, status_msg: str = ""):
    telemetry = asv.get_telemetry()
    arm_str = "ARMED 🟢" if telemetry.is_armed else "DISARMED 🔴"
    conn_str = "TERHUBUNG 🟢" if telemetry.is_connected else "TERPUTUS 🔴"
    track_str = "AKTIF 🟢 (AUTONOMOUS)" if auto_tracking_active else "NON-AKTIF 🔴 (MANUAL PAUSE)"

    gate_x = last_detection.get("gate_x")
    error_px = last_detection.get("error_px")
    speed_out = last_detection.get("speed_out", 0.0)
    turn_out = last_detection.get("turn_out", 0.0)
    direction_str = last_detection.get("direction", "NO OBJECT")

    print("==================================================================")
    print(" 🚢 ASV YOLO OBJECT DETECTION + VISUAL PID TRACKING UI")
    print("==================================================================")
    print(f" Status FC   : {conn_str:<12} | Mode FC    : {telemetry.mode:<10}")
    print(f" Arming      : {arm_str:<12} | Auto Track : {track_str}")
    print(f" GPS Fix     : Lat={telemetry.lat:.7f}, Lon={telemetry.lon:.7f}")
    print(f" Heading     : {telemetry.heading:.1f}°         | Speed Real : {telemetry.ground_speed:.2f} m/s")
    print("------------------------------------------------------------------")
    print(f" 🎯 VISUAL TARGET : Gate Center X = {str(gate_x):<8} | Error Px = {str(error_px):<8}")
    print(f" 🕹️ PID OUTPUT    : Speed = {speed_out:.2f} m/s     | Turn Rate = {turn_out:+.1f}°/s")
    print(f" 🧭 ARAH GERAK    : {direction_str}")
    print("------------------------------------------------------------------")
    print(f" ⚙️ PID TUNING   : Kp={kp_val:.3f} | Ki={ki_val:.3f} | Kd={kd_val:.3f} | Speed={target_speed:.1f}m/s")
    print("------------------------------------------------------------------")
    print(" 🎮 CONTROL COMMANDS:")
    print("   [ 1 ] 🚀 ARM Kapal                [ 2 ] 🔴 DISARM Kapal")
    print("   [ 3 ] 🔵 Mode GUIDED             [ 4 ] 🟡 Mode MANUAL")
    print("   [ t ] 🔄 TOGGLE AUTO TRACKING (ON/OFF)")
    print("")
    print(" 🔧 LIVE PID & SPEED TUNING:")
    print("   [ + ] Target Speed +0.1 m/s       [ - ] Target Speed -0.1 m/s")
    print("   [ [ ] Kp Gain -0.005              [ ] ] Kp Gain +0.005")
    print("   [ s ] 🛑 STOP SEMENTARA (Hold 0 m/s)")
    print("   [ q ] 🚪 Keluar Program")
    print("==================================================================")
    if status_msg:
        print(f" 💬 STATUS LOG : {status_msg}")
        print("------------------------------------------------------------------")

def get_char():
    """Membaca 1 karakter dari terminal secara langsung (Linux)."""
    try:
        import tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch
    except Exception:
        return input(" Masukkan Perintah: ").strip()

def main():
    global target_speed, kp_val, ki_val, kd_val, max_turn_val
    global running, auto_tracking_active
    signal.signal(signal.SIGINT, signal_handler)

    port = os.getenv("ASV_TEST_PORT", "/dev/ttyACM0")
    baud = int(os.getenv("ASV_TEST_BAUD", "9600"))
    cam_idx = int(os.getenv("ASV_CAM_IDX", "0"))

    print("[UI] Memulai ASV Controller & MAVLink...")
    asv = ASVController(port=port, baudrate=baud)
    asv.start()

    print("[UI] Menunggu heartbeat dari Pixhawk...")
    start_wait = time.time()
    while running and not asv.is_connected():
        if time.time() - start_wait > 15:
            print("[UI] ❌ Timeout: Pixhawk tidak terdeteksi dalam 15 detik.")
            asv.stop()
            return
        time.sleep(1.0)

    # Sinkronisasi parameter speed controller Pixhawk
    asv.configure_guided_parameters(cruise_speed=target_speed, cruise_throttle=50.0, atc_speed_p=1.0)

    print("[UI] Loading YOLO BallTracker model...")
    model_path = os.path.join(os.path.dirname(__file__), "models", "best.pt")
    tracker = BallTracker(model_path=model_path, target_class=[0, 1], conf_threshold=0.75)

    print("[UI] Inisialisasi Visual PID TrackingController...")
    controller = TrackingController(
        frame_width=640,
        kp=kp_val,
        ki=ki_val,
        kd=kd_val,
        forward_speed=target_speed,
        max_turn_rate=max_turn_val
    )

    # Open Camera
    cap = cv2.VideoCapture(cam_idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print(f"[UI] ⚠️ Kamera index {cam_idx} gagal dibuka. Tracking visual akan berjalan tanpa kamera aktif.")

    last_detection = {
        "gate_x": None,
        "error_px": None,
        "speed_out": 0.0,
        "turn_out": 0.0,
        "direction": "NO OBJECT DETECTED"
    }

    status_msg = "Sistem Kamera & PID Tracking SIAP! Tekan 't' untuk mengaktifkan Auto Tracking."

    # Background Thread untuk Loop Vision + PID Tracking
    def vision_pid_loop():
        nonlocal last_detection
        while running:
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    # Deteksi Gate Buoy
                    processed_frame, gate_x, gate_y = tracker.process_frame(frame)

                    if gate_x is not None:
                        error_px = int(gate_x - 320)
                        speed, turn_rate, state = controller.compute_velocity(gate_x)

                        # Tentukan keterangan arah
                        if turn_rate > 3.0:
                            direction = f"➡️ BELOK KANAN (+{turn_rate:.1f}°/s)"
                        elif turn_rate < -3.0:
                            direction = f"⬅️ BELOK KIRI ({turn_rate:.1f}°/s)"
                        else:
                            direction = f"⬆️ MAJU LURUS PRESI (Turn: {turn_rate:.1f}°/s)"

                        last_detection = {
                            "gate_x": int(gate_x),
                            "error_px": error_px,
                            "speed_out": speed,
                            "turn_out": turn_rate,
                            "direction": direction
                        }

                        # Kirim Perintah ke Pixhawk jika Auto Tracking AKTIF, ARMED, dan GUIDED
                        if auto_tracking_active and asv.is_connected():
                            telemetry = asv.get_telemetry()
                            if telemetry.is_armed and telemetry.mode == "GUIDED":
                                asv.turn(speed, turn_rate)
                    else:
                        last_detection = {
                            "gate_x": None,
                            "error_px": None,
                            "speed_out": 0.0,
                            "turn_out": 0.0,
                            "direction": "🔴 TIDAK ADA GATE BUOY DETECTED"
                        }
                        if auto_tracking_active and asv.is_connected():
                            telemetry = asv.get_telemetry()
                            if telemetry.is_armed and telemetry.mode == "GUIDED":
                                asv.stop_movement(silent=True)

                    # Tampilkan GUI Window OpenCV untuk visualisasi frame kamera & YOLO detection
                    try:
                        cv2.imshow("ASV YOLO Gate Tracking", processed_frame)
                        cv2.waitKey(1)
                    except Exception:
                        pass

            time.sleep(0.03)  # ~30 FPS loop

    try:
        cv2.startWindowThread()
    except Exception:
        pass

    vision_thread = threading.Thread(target=vision_pid_loop, daemon=True)
    vision_thread.start()

    while running:
        clear_screen()
        render_ui(asv, last_detection, status_msg)

        print(" Pilih Perintah [1/2/3/4/t/+/ -/[/]/s/q]: ", end="", flush=True)
        key = get_char().lower()

        if key == 'q' or key == '\x03':
            status_msg = "Menghentikan program..."
            break

        # --- ARMING & MODES ---
        elif key == '1':
            asv.arm(force=True)
            status_msg = "Perintah MAVLink ARM dikirim!"

        elif key == '2':
            auto_tracking_active = False
            asv.disarm(force=True)
            status_msg = "Perintah MAVLink DISARM dikirim! Auto-tracking dimatikan."

        elif key == '3':
            asv.set_mode("GUIDED")
            status_msg = "Switched to GUIDED Mode!"

        elif key == '4':
            auto_tracking_active = False
            asv.set_mode("MANUAL")
            status_msg = "Switched to MANUAL Mode! Auto-tracking dimatikan."

        # --- TOGGLE AUTO TRACKING ---
        elif key == 't':
            auto_tracking_active = not auto_tracking_active
            if auto_tracking_active:
                if not asv.get_telemetry().is_armed:
                    asv.arm(force=True)
                if asv.get_telemetry().mode != "GUIDED":
                    asv.set_mode("GUIDED")
                status_msg = "🚀 AUTO TRACKING ACTIVATED! Kapal mengikuti Gate Buoy via PID!"
            else:
                asv.stop_movement()
                status_msg = "🛑 AUTO TRACKING DEACTIVATED! Pergerakan dihentikan."

        elif key == 's':
            auto_tracking_active = False
            asv.stop_movement()
            status_msg = "🛑 STOP MOVEMENT & PAUSE TRACKING."

        # --- PID TUNING ---
        elif key == '+' or key == '=':
            target_speed = round(min(2.0, target_speed + 0.1), 2)
            controller.update_pid_params(forward_speed=target_speed)
            status_msg = f" ⚙️ Target Speed dinaikkan ke: {target_speed:.1f} m/s"

        elif key == '-':
            target_speed = round(max(0.1, target_speed - 0.1), 2)
            controller.update_pid_params(forward_speed=target_speed)
            status_msg = f" ⚙️ Target Speed diturunkan ke: {target_speed:.1f} m/s"

        elif key == '[':
            kp_val = round(max(0.005, kp_val - 0.005), 3)
            controller.update_pid_params(kp=kp_val)
            status_msg = f" ⚙️ Kp Gain diturunkan ke: {kp_val:.3f}"

        elif key == ']':
            kp_val = round(min(0.2, kp_val + 0.005), 3)
            controller.update_pid_params(kp=kp_val)
            status_msg = f" ⚙️ Kp Gain dinaikkan ke: {kp_val:.3f}"

        time.sleep(0.1)

    # Cleanup
    auto_tracking_active = False
    print("\n[UI] Menghentikan kapal dan membersihkan koneksi...")
    if cap.isOpened():
        cap.release()
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass
    try:
        asv.stop_movement()
        asv.disarm(force=True)
    except Exception:
        pass
    asv.stop()
    print("[UI] Selesai.")

if __name__ == "__main__":
    main()
