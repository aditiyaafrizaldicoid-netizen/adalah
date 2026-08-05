#!/usr/bin/env python3
"""
=============================================================================
 🚢 INTERACTIVE GUIDED MODE CONTROL UI (MAVLink Only)
=============================================================================
 Interface Interaktif berbasis Terminal untuk menguji dan mengendalikan 
 Mode GUIDED & Navigasi MAVLink kapal ASV secara langsung (real-time).

 Sesuai dengan Sistem Directives (AGENTS.md):
 - NO DIRECT MOTOR/SERVO OVERRIDE dalam mode otonom.
 - Seluruh pergerakan dikirim via MAVLink SET_POSITION_TARGET_LOCAL_NED.
=============================================================================
"""

import sys
sys.dont_write_bytecode = True  # Mencegah pemuatan file cache __pycache__ / .pyc

import os
import time
import signal
import threading
from core.client import ASVController

# Settings Default
target_speed = 1.0       # m/s
target_turn_rate = 15.0  # deg/s
running = True

# Continuous Drive Streamer state
current_drive_speed = 0.0
current_drive_turn_rate = 0.0
drive_active = False

def signal_handler(sig, frame):
    global running
    print("\n[UI] ⚠️ Menutup program interaktif...")
    running = False

def velocity_streamer(asv: ASVController):
    global current_drive_speed, current_drive_turn_rate, drive_active, running
    while running:
        if drive_active and asv.is_connected():
            telemetry = asv.get_telemetry()
            if telemetry.is_armed and telemetry.mode == "GUIDED":
                asv.turn(current_drive_speed, current_drive_turn_rate)
        time.sleep(0.2)  # 5 Hz streaming rate

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def render_ui(asv: ASVController, status_msg: str = ""):
    telemetry = asv.get_telemetry()
    arm_str = "ARMED 🟢" if telemetry.is_armed else "DISARMED 🔴"
    conn_str = "TERHUBUNG 🟢" if telemetry.is_connected else "TERPUTUS 🔴"
    
    print("==================================================================")
    print(" 🚢 ASV GUIDED MODE INTERACTIVE CONTROL UI")
    print("==================================================================")
    print(f" Status FC  : {conn_str:<12} | Mode FC   : {telemetry.mode:<10}")
    print(f" Arming     : {arm_str:<12} | Baterai   : {telemetry.battery_voltage:.2f} V")
    print(f" GPS Fix    : Lat={telemetry.lat:.7f}, Lon={telemetry.lon:.7f}")
    print(f" Heading    : {telemetry.heading:.1f}°         | Speed Real: {telemetry.ground_speed:.2f} m/s")
    print("------------------------------------------------------------------")
    print(f" ⚙️ TARGET TUNING: Kecepatan = {target_speed:.1f} m/s | Turn Rate = ±{target_turn_rate:.1f}°/s")
    print("------------------------------------------------------------------")
    print(" 🎮 PERINTAH KONTROL:")
    print("   [ 1 ] 🚀 ARM Kapal (Pure MAVLink) [ 2 ] 🔴 DISARM Kapal")
    print("   [ 3 ] 🔵 Mode GUIDED              [ 4 ] 🟡 Mode MANUAL")
    print("")
    print(" 🕹️ KEMUDI / DRIVE (Mode GUIDED):")
    print("   [ w ] ⬆️ Maju Lurus (Speed)        [ s ] 🛑 STOP (Hold 0 m/s)")
    print("   [ a ] ⬅️ Belok Kiri (-Rate)         [ d ] ➡️ Belok Kanan (+Rate)")
    print("   [ x ] ⬇️ Mundur Pelan (-Speed)")
    print("")
    print(" 🔧 TUNING & WAYPOINT:")
    print("   [ + ] Kecepatan +0.2 m/s           [ - ] Kecepatan -0.2 m/s")
    print("   [ [ ] Turn Rate -5.0°/s            [ ] ] Turn Rate +5.0°/s")
    print("   [ g ] 🧭 Kirim GOTO GPS Target     [ q ] 🚪 Keluar Program")
    print("==================================================================")
    if status_msg:
        print(f" 💬 LAST STATUS: {status_msg}")
        print("------------------------------------------------------------------")

def get_char():
    """Membaca 1 karakter dari terminal secara langsung tanpa perlu tombol Enter (Linux)."""
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
    global target_speed, target_turn_rate, running
    global current_drive_speed, current_drive_turn_rate, drive_active
    signal.signal(signal.SIGINT, signal_handler)

    port = os.getenv("ASV_TEST_PORT", "/dev/ttyACM0")
    baud = int(os.getenv("ASV_TEST_BAUD", "9600"))

    print("[UI] Memulai ASV Controller...")
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

    # Automatically set Pixhawk Speed Controller parameters for Guided Mode
    asv.configure_guided_parameters(cruise_speed=target_speed, cruise_throttle=50.0, atc_speed_p=1.0)

    # Start background velocity streamer thread for continuous Guided movement
    stream_thread = threading.Thread(target=velocity_streamer, args=(asv,), daemon=True)
    stream_thread.start()

    status_msg = "Sistem terhubung ke Pixhawk. SIAP DICOBA!"

    while running:
        clear_screen()
        render_ui(asv, status_msg)
        
        print(" Pilih Aksi [w/a/s/d/x/1/2/3/4/+/ -/g/q]: ", end="", flush=True)
        key = get_char().lower()

        if key == 'q' or key == '\x03':
            status_msg = "Menghentikan program..."
            break

        # --- MODE & ARMING ---
        elif key == '1':
            asv.arm(force=True)
            status_msg = "Perintah MAVLink ARM (force=True) dikirim!"

        elif key == '2':
            drive_active = False
            asv.disarm(force=True)
            status_msg = "Perintah MAVLink DISARM dikirim!"

        elif key == '3':
            asv.set_mode("GUIDED")
            status_msg = "Perintah Mode GUIDED dikirim!"

        elif key == '4':
            drive_active = False
            asv.set_mode("MANUAL")
            status_msg = "Perintah Mode MANUAL dikirim!"

        # --- GUIDED DRIVE COMMANDS ---
        elif key in ['w', 'a', 'd', 'x']:
            if not asv.get_telemetry().is_armed:
                asv.arm(force=True)
                time.sleep(0.1)
            if asv.get_telemetry().mode != "GUIDED":
                asv.set_mode("GUIDED")
                time.sleep(0.1)

            if key == 'w':
                current_drive_speed = target_speed
                current_drive_turn_rate = 0.0
                drive_active = True
                status_msg = f" ⬆️ Maju Lurus (Speed: {target_speed:.1f} m/s)"
            elif key == 'a':
                current_drive_speed = target_speed
                current_drive_turn_rate = -target_turn_rate
                drive_active = True
                status_msg = f" ⬅️ Belok Kiri (Speed: {target_speed:.1f} m/s, Turn Rate: -{target_turn_rate:.1f}°/s)"
            elif key == 'd':
                current_drive_speed = target_speed
                current_drive_turn_rate = target_turn_rate
                drive_active = True
                status_msg = f" ➡️ Belok Kanan (Speed: {target_speed:.1f} m/s, Turn Rate: +{target_turn_rate:.1f}°/s)"
            elif key == 'x':
                current_drive_speed = -0.5
                current_drive_turn_rate = 0.0
                drive_active = True
                status_msg = f" ⬇️ Mundur Pelan (-0.5 m/s)"

        elif key == 's':
            drive_active = False
            current_drive_speed = 0.0
            current_drive_turn_rate = 0.0
            asv.stop_movement()
            status_msg = " 🛑 STOP MOVEMENT (Kecepatan = 0 m/s)"

        # --- SPEED TUNING ---
        elif key == '+' or key == '=':
            target_speed = min(3.0, target_speed + 0.2)
            if drive_active and current_drive_speed > 0:
                current_drive_speed = target_speed
            status_msg = f" ⚙️ Target Speed dinaikkan ke: {target_speed:.1f} m/s"

        elif key == '-':
            target_speed = max(0.2, target_speed - 0.2)
            if drive_active and current_drive_speed > 0:
                current_drive_speed = target_speed
            status_msg = f" ⚙️ Target Speed diturunkan ke: {target_speed:.1f} m/s"

        elif key == '[':
            target_turn_rate = max(5.0, target_turn_rate - 5.0)
            if drive_active and current_drive_turn_rate != 0:
                current_drive_turn_rate = -target_turn_rate if current_drive_turn_rate < 0 else target_turn_rate
            status_msg = f" ⚙️ Target Turn Rate diturunkan ke: {target_turn_rate:.1f}°/s"

        elif key == ']':
            target_turn_rate = min(60.0, target_turn_rate + 5.0)
            if drive_active and current_drive_turn_rate != 0:
                current_drive_turn_rate = -target_turn_rate if current_drive_turn_rate < 0 else target_turn_rate
            status_msg = f" ⚙️ Target Turn Rate dinaikkan ke: {target_turn_rate:.1f}°/s"

        # --- GOTO GPS ---
        elif key == 'g':
            drive_active = False
            current_t = asv.get_telemetry()
            lat = current_t.lat if current_t.lat != 0 else -7.9215169
            lon = (current_t.lon + 0.0001) if current_t.lon != 0 else 112.5973649
            asv.goto(lat, lon)
            status_msg = f" 🧭 Perintah GOTO dikirim ke Lat={lat:.7f}, Lon={lon:.7f}"

        else:
            status_msg = f" Perintah '{key}' tidak dikenali. Gunakan tombol menu yang tersedia."

        time.sleep(0.1)

    # Cleanup
    drive_active = False
    print("\n[UI] Menghentikan kapal dan membersihkan koneksi...")
    try:
        asv.stop_movement()
        asv.disarm(force=True)
    except Exception:
        pass
    asv.stop()
    print("[UI] Selesai.")

if __name__ == "__main__":
    main()
