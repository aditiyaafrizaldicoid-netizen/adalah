#!/usr/bin/env python3
"""
=============================================================================
 🚢 INTERACTIVE AI BOAT CONTROL UI IN MANUAL MODE (RC OVERRIDE)
=============================================================================
 Script Interaktif Terminal untuk menguji kendali AI kapal otonom secara penuh
 dalam MANUAL Mode via MAVLink RC_CHANNELS_OVERRIDE.

 Mengapa MANUAL Mode?
 - Menghindari interference Heading Controller bawaan ArduPilot.
 - Jetson bertindak sebagai pengambil keputusan penuh.

 Channel Mapping:
 - Channel 1 (RCIN1 / Roll)    : Steering Kemudi Servo (1000us Kiri, 1500us Netral, 2000us Kanan)
 - Channel 3 (RCIN3 / Throttle): ESC Motor Thruster (1000us Stop/0%, 2000us Full/100%)

 Speed Scheduler:
 - Steering < 0.10  -> Throttle 80% (PWM ~1800 us)
 - Steering < 0.30  -> Throttle 65% (PWM ~1650 us)
 - Steering < 0.60  -> Throttle 50% (PWM ~1500 us)
 - Steering >= 0.60 -> Throttle 30% (PWM ~1300 us - Belokan Tajam Kecepatan Rendah)
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
from control.speed_scheduler import SpeedScheduler, YawRateSpeedScheduler

# State Program
running = True
ai_manual_active = False

# Controller Settings Default
max_base_throttle = 0.4  # 100% Max Throttle Scale
kp_val = 0.051
ki_val = 0.000
kd_val = 0.000
max_turn_val = 40.0

def signal_handler(sig, frame):
    global running
    print("\n[UI] ⚠️ Menutup program AI MANUAL Control...")
    running = False

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def render_ui(asv: ASVController, last_state: dict, status_msg: str = ""):
    telemetry = asv.get_telemetry()
    arm_str = "ARMED 🟢" if telemetry.is_armed else "DISARMED 🔴"
    conn_str = "TERHUBUNG 🟢" if telemetry.is_connected else "TERPUTUS 🔴"
    ai_str = "AKTIF 🟢 (AI FULL CONTROL)" if ai_manual_active else "NON-AKTIF 🔴 (PAUSED)"

    gate_x = last_state.get("gate_x")
    error_px = last_state.get("error_px")
    steer_norm = last_state.get("steer_norm", 0.0)
    thr_norm = last_state.get("thr_norm", 0.0)
    pwm_ch1 = last_state.get("pwm_ch1", 1500)
    pwm_ch3 = last_state.get("pwm_ch3", 1000)
    scheduler_rule = last_state.get("scheduler_rule", "STOP")

    print("==================================================================")
    print(" 🚢 ASV MANUAL MODE AI CONTROL (RC OVERRIDE CH1 & CH3)")
    print("==================================================================")
    print(f" Status FC   : {conn_str:<12} | Mode FC    : {telemetry.mode:<10}")
    print(f" Arming      : {arm_str:<12} | AI Control : {ai_str}")
    print(f" GPS Fix     : Lat={telemetry.lat:.7f}, Lon={telemetry.lon:.7f}")
    print(f" Heading     : {telemetry.heading:.1f}°         | Speed Real : {telemetry.ground_speed:.2f} m/s")
    print("------------------------------------------------------------------")
    print(f" 🎯 VISUAL TARGET : Gate Center X = {str(gate_x):<8} | Error Px = {str(error_px):<8}")
    print(f" 🕹️ STEERING (Ch1): {steer_norm:+.2f}              | PWM Ch 1  = {pwm_ch1} µs (Roll/Steer)")
    print(f" 🚀 THROTTLE (Ch3): {thr_norm*100:3.0f}%               | PWM Ch 3  = {pwm_ch3} µs (ESC Motor)")
    print(f" ⚡ SPEED SCHEDULER: {scheduler_rule}")
    print("------------------------------------------------------------------")
    print(f" ⚙️ TUNING      : Kp={kp_val:.3f} | Max Throttle Scale={max_base_throttle*100:.0f}%")
    print("------------------------------------------------------------------")
    print(" 🎮 CONTROL COMMANDS:")
    print("   [ 1 ] 🚀 ARM Kapal                [ 2 ] 🔴 DISARM Kapal")
    print("   [ 4 ] 🟡 Mode MANUAL (Wajib)      [ t ] 🔄 TOGGLE AI CONTROL (ON/OFF)")
    print("")
    print(" 🔧 LIVE SPEED & PID TUNING:")
    print("   [ + ] Max Throttle +1%            [ - ] Max Throttle -1%")
    print("   [ [ ] Kp Gain -0.001              [ ] ] Kp Gain +0.001")
    print("   [ s ] 🛑 EMERGENCY STOP (Throttle 1000us, Steer 1500us)")
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
    global max_base_throttle, kp_val, ki_val, kd_val, max_turn_val
    global running, ai_manual_active
    signal.signal(signal.SIGINT, signal_handler)

    port = os.getenv("ASV_TEST_PORT", "/dev/ttyACM0")
    baud = int(os.getenv("ASV_TEST_BAUD", "115200"))
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

    # Inisialisasi Modul Vision, PID, dan Speed Scheduler
    model_path = os.path.join(os.path.dirname(__file__), "models", "best.pt")
    tracker = BallTracker(model_path=model_path, target_class=[0, 1], conf_threshold=0.7)

    controller = TrackingController(
        frame_width=640,
        kp=kp_val,
        ki=ki_val,
        kd=kd_val,
        max_turn_rate=max_turn_val
    )

    scheduler = SpeedScheduler(max_base_throttle=max_base_throttle)

    # Open Camera
    cap = cv2.VideoCapture(cam_idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print(f"[UI] ⚠️ Kamera index {cam_idx} gagal dibuka. Kamera visual tidak aktif.")

    last_state = {
        "gate_x": None,
        "error_px": None,
        "steer_norm": 0.0,
        "thr_norm": 0.0,
        "pwm_ch1": 1500,
        "pwm_ch3": 1000,
        "scheduler_rule": "NO TARGET"
    }

    status_msg = "Sistem AI MANUAL Control SIAP! Pindah ke Mode MANUAL [4], ARM [1], lalu tekan 't' untuk mengaktifkan AI."

    # Background Thread untuk Loop Vision + PID + Speed Scheduler + RC Override
    def ai_control_loop():
        nonlocal last_state
        while running:
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    # 1. Vision: YOLO Detection
                    processed_frame, gate_x, gate_y = tracker.process_frame(frame)

                    target_present = (gate_x is not None)
                    if target_present:
                        error_px = int(gate_x - 320)

                        # 2. PID: Compute Normalized Steering (-1.0 s/d +1.0)
                        steer_norm = controller.compute_normalized_steering(gate_x)

                        # 3. Speed Scheduler: Compute Throttle Ratio (0.0 s/d 1.0)
                        thr_norm = scheduler.compute_throttle(steer_norm, target_present=True)

                        # Hitung PWM aktual
                        pwm_ch1 = int(1500 + (steer_norm * 500.0))
                        pwm_ch3 = int(1000 + (thr_norm * 1000.0))

                        abs_s = abs(steer_norm)
                        if abs_s < 0.10:
                            rule = "HIGH SPEED 80% (Straight Ahead)"
                        elif abs_s < 0.30:
                            rule = "MED-HIGH 65% (Mild Curve)"
                        elif abs_s < 0.60:
                            rule = "MED SPEED 45% (Moderate Turn)"
                        else:
                            rule = "LOW SPEED 25% (Sharp Turn)"

                        last_state = {
                            "gate_x": int(gate_x),
                            "error_px": error_px,
                            "steer_norm": steer_norm,
                            "thr_norm": thr_norm,
                            "pwm_ch1": pwm_ch1,
                            "pwm_ch3": pwm_ch3,
                            "scheduler_rule": rule
                        }

                        # 4. Kirim RC Override jika AI Control AKTIF, ARMED, dan Mode MANUAL
                        if ai_manual_active and asv.is_connected():
                            telemetry = asv.get_telemetry()
                            if telemetry.is_armed and telemetry.mode == "MANUAL":
                                asv.send_manual_rc_drive(steer_norm, thr_norm)
                    else:
                        # FAILSAFE: Target tidak terdeteksi -> Stop motor (1000us) & Steer Netral (1500us)
                        last_state = {
                            "gate_x": None,
                            "error_px": None,
                            "steer_norm": 0.0,
                            "thr_norm": 0.0,
                            "pwm_ch1": 1500,
                            "pwm_ch3": 1000,
                            "scheduler_rule": "🔴 FAILSAFE: TARGET LOST (Stop Motor)"
                        }

                        if ai_manual_active and asv.is_connected():
                            telemetry = asv.get_telemetry()
                            if telemetry.is_armed and telemetry.mode == "MANUAL":
                                asv.send_manual_rc_drive(0.0, 0.0)

                    # Draw OSD pada frame OpenCV
                    osd_text = f"AI MANUAL: STEER {last_state['steer_norm']:+.2f} (Ch1:{last_state['pwm_ch1']}us) | THR {last_state['thr_norm']*100:.0f}% (Ch3:{last_state['pwm_ch3']}us)"
                    cv2.putText(processed_frame, osd_text, (10, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 2)

                    # Display OpenCV Window
                    try:
                        cv2.imshow("ASV MANUAL AI Boat Control (Ch1 Roll / Ch3 Thr)", processed_frame)
                        cv2.waitKey(1)
                    except Exception:
                        pass

            time.sleep(0.03)  # 30 FPS Control Loop

    try:
        cv2.startWindowThread()
    except Exception:
        pass

    ai_thread = threading.Thread(target=ai_control_loop, daemon=True)
    ai_thread.start()

    while running:
        clear_screen()
        render_ui(asv, last_state, status_msg)

        print(" Pilih Perintah [1/2/4/t/+/ -/[/]/s/q]: ", end="", flush=True)
        key = get_char().lower()

        if key == 'q' or key == '\x03':
            status_msg = "Menghentikan program..."
            break

        elif key == '1':
            asv.arm(force=True)
            status_msg = "Perintah MAVLink ARM dikirim!"

        elif key == '2':
            ai_manual_active = False
            asv.send_manual_rc_drive(0.0, 0.0)
            asv.disarm(force=True)
            status_msg = "Perintah MAVLink DISARM dikirim! AI Control dimatikan."

        elif key == '4':
            asv.set_mode("MANUAL")
            status_msg = "Switched to MANUAL Mode!"

        elif key == 't':
            ai_manual_active = not ai_manual_active
            if ai_manual_active:
                if not asv.get_telemetry().is_armed:
                    asv.arm(force=True)
                if asv.get_telemetry().mode != "MANUAL":
                    asv.set_mode("MANUAL")
                status_msg = "🚀 AI MANUAL CONTROL ACTIVATED! Sinyal RC Override Ch1 & Ch3 dikirim ke Pixhawk!"
            else:
                asv.send_manual_rc_drive(0.0, 0.0)
                status_msg = "🛑 AI MANUAL CONTROL DEACTIVATED! Motor dihentikan."

        elif key == 's':
            ai_manual_active = False
            asv.send_manual_rc_drive(0.0, 0.0)
            status_msg = "🛑 EMERGENCY STOP: Throttle 1000us, Steering 1500us."

        elif key == '+' or key == '=':
            max_base_throttle = round(min(1.0, max_base_throttle + 0.01), 2)
            scheduler.max_base_throttle = max_base_throttle
            status_msg = f" ⚙️ Max Base Throttle Scale dinaikkan ke: {max_base_throttle*100:.0f}%"

        elif key == '-':
            max_base_throttle = round(max(0.01, max_base_throttle - 0.01), 2)
            scheduler.max_base_throttle = max_base_throttle
            status_msg = f" ⚙️ Max Base Throttle Scale diturunkan ke: {max_base_throttle*100:.0f}%"

        elif key == '[':
            kp_val = round(max(0.001, kp_val - 0.001), 3)
            controller.update_pid_params(kp=kp_val)
            status_msg = f" ⚙️ Kp Gain diturunkan ke: {kp_val:.3f}"

        elif key == ']':
            kp_val = round(min(50.0, kp_val + 0.001), 3)
            controller.update_pid_params(kp=kp_val)
            status_msg = f" ⚙️ Kp Gain dinaikkan ke: {kp_val:.3f}"

        time.sleep(0.1)

    # Cleanup
    ai_manual_active = False
    print("\n[UI] Menghentikan kapal dan membersihkan koneksi...")
    if cap.isOpened():
        cap.release()
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass
    try:
        asv.send_manual_rc_drive(0.0, 0.0)
        asv.release_rc()
        asv.disarm(force=True)
    except Exception:
        pass
    asv.stop()
    print("[UI] Selesai.")

if __name__ == "__main__":
    main()
