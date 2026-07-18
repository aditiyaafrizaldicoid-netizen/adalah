import time
import os
from client import ASVController

def run_test():
    print("==================================================")
    print(" 🚢 ASV FLIGHT CONTROLLER ONBOARD TEST SCRIPT ")
    print("==================================================")
    
    # Ganti dengan port yang sesuai di Mini PC (misal "/dev/ttyACM0" atau "udp:127.0.0.1:14550" untuk SITL)
    port = os.getenv("ASV_TEST_PORT", "/dev/ttyACM0")
    baudrate = 9600
    
    asv = ASVController(port=port, baudrate=baudrate)
    
    try:
        # 1. Mulai background connection & polling
        asv.start()
        
        # 2. Loop pemantauan telemetri selama beberapa detik
        print("\n[Test] Memantau telemetri selama 10 detik...")
        while True:
            telemetry = asv.get_telemetry()
            status_str = "CONNECTED 🟢" if telemetry.is_connected else "DISCONNECTED 🔴"
            print(f"[+] Status: {status_str} | Mode: {telemetry.mode} | Armed: {telemetry.is_armed}")
            if telemetry.is_connected:
                print(f"       GPS: ({telemetry.lat:.6f}, {telemetry.lon:.6f}) Alt: {telemetry.alt:.1f}m | Yaw: {telemetry.yaw:.1f}° Roll: {telemetry.roll:.1f}° Pitch: {telemetry.pitch:.1f}° | Heading: {telemetry.heading:.1f}° ")
                print(f"       Vel: ({telemetry.vx:.2f}, {telemetry.vy:.2f}, {telemetry.vz:.2f}) m/s | Speed: {telemetry.ground_speed:.2f} m/s | Baterai: {telemetry.battery_voltage:.2f}V ({telemetry.battery_remaining}%)")
            time.sleep(1.0)
            
        # 3. Contoh pengiriman perintah (DIBATASI: Hanya tes ganti mode dan ARM jika diminta)
        print("\n[Test] Contoh panggilan metode kontrol (tidak dikirim jika tidak terhubung):")
        if asv.is_connected():
            print(" -> [Info] Untuk menguji pergerakan di air/SITL (Mode GUIDED):")
            print("           asv.arm()")
            print("           asv.set_mode('GUIDED')")
            print("           asv.move_forward(speed=1.0)")
            print(" -> [Info] Untuk menguji kendali 2 Thruster + 2 Servo Steering (Mode MANUAL):")
            print("           asv.set_mode('MANUAL')")
            print("           # Contoh: Thruster Kiri & Kanan maju ringan (1600), Servo belok kanan (1700)")
            print("           asv.drive_dual_vectored(throttle_left=1600, throttle_right=1600, servo_left=1700, servo_right=1700)")
            print("           # Atau gerakkan satu servo langsung (contoh Channel 1 PWM 1800)")
            print("           asv.set_servo(channel=1, pwm=1800)")
            print("           asv.release_rc() # Lepaskan kendali saat selesai")
        else:
            print(" -> [Info] Pixhawk belum terdeteksi di port tersebut. Cek kabel USB atau konfigurasi port.")

    except KeyboardInterrupt:
        print("\n[Test] Dibatalkan oleh pengguna.")
    finally:
        # 4. Tutup koneksi dengan rapi
        asv.stop()
        print("\n[Test] Selesai. Koneksi ditutup.")

if __name__ == "__main__":
    run_test()
