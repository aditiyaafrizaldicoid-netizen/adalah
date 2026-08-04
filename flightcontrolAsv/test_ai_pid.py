import os
os.environ['QT_LOGGING_RULES'] = 'qt.qpa.fonts.warning=false;qt.qpa.*=false'
import cv2
import time
import sys
from vision.tracker import BallTracker
from control.pid_tracker import TrackingController

def test_ai_pid():
    print("==================================================")
    print(" 🧪 TEST PROGRAM: AI (YOLO) & PID Controller ")
    print("==================================================")
    
    # 1. Inisialisasi Tracker (menggunakan best.pt sesuai permintaan)
    model_path = "best.pt"
    # Model Anda memiliki 2 kelas: 0='B_GREEN', 1='B_RED'
    # Menggunakan list [0, 1] agar mendeteksi bola hijau maupun merah
    target_class = [0, 1] 
    print(f"[*] Inisialisasi YOLOv8 dengan model: {model_path}")
    
    try:
        tracker = BallTracker(model_path=model_path, target_class=target_class, conf_threshold=0.6)
    except Exception as e:
        print(f"[!] Gagal memuat model YOLO: {e}")
        return

    # 2. Inisialisasi PID Controller
    camera_width = 640
    camera_height = 320
    print(f"[*] Inisialisasi PID Controller (SetPoint Center X: {camera_width//2})")
    controller = TrackingController(frame_width=camera_width, kp=0.4, ki=0.0, kd=0.1)

    # 3. Buka Kamera
    camera_index = 2
    print(f"[*] Membuka kamera index {camera_index}...")
    cap = cv2.VideoCapture(camera_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_height)
    
    if not cap.isOpened():
        print(f"[!] Gagal membuka kamera {camera_index}!")
        return
        
    print("\n[+] Sistem siap. Memulai deteksi dan logging (Tekan Ctrl+C untuk berhenti)...\n")
    print(f"{'TIME':<10} | {'BALL X':<8} | {'ERROR':<8} | {'PID OUT':<8} | {'PWM (STEER)':<12}")
    print("-" * 60)
    
    start_time = time.time()
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[!] Gagal membaca frame dari kamera.")
                time.sleep(1)
                continue
                
            # Resize frame to match expected width/height
            if frame.shape[1] != camera_width or frame.shape[0] != camera_height:
                frame = cv2.resize(frame, (camera_width, camera_height))
            
            # Proses deteksi AI
            processed_frame, ball_x, ball_y = tracker.process_frame(frame)
            
            # Hitung PID & PWM
            steering_pwm, is_tracking = controller.compute_steering(ball_x)
            
            # Waktu berjalan
            elapsed = time.time() - start_time
            t_str = f"{elapsed:.1f}s"
            
            # Tampilkan Logging
            if ball_x is not None:
                # Error: Seberapa jauh bola dari tengah (Setpoint - Input)
                error = controller.center_x - ball_x
                
                # Mendapatkan nilai PID mentah dari atribut internal
                # output_pid adalah hasil -pid(ball_x) pada pid_tracker
                pid_out = steering_pwm - 1500
                
                print(f"{t_str:<10} | {ball_x:<8} | {error:<8} | {pid_out:<8} | {steering_pwm:<12}")
            else:
                if is_tracking:
                    print(f"{t_str:<10} | {'NONE':<8} | {'---':<8} | {'---':<8} | {steering_pwm:<12} (HOLD)")
                else:
                    print(f"{t_str:<10} | {'NONE':<8} | {'---':<8} | {'---':<8} | {1500:<12} (NEUTRAL)")
                    
            # Tampilkan frame GUI (jika didukung)
            try:
                cv2.imshow("AI & PID Test", processed_frame)
                # Tekan 'q' pada jendela video untuk keluar
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            except cv2.error:
                print("\n[!] Tidak dapat membuka jendela video GUI.")
                print("Jika Anda ingin melihat video, Anda perlu mengganti paket OpenCV headless dengan paket GUI.")
                print("Jalankan perintah ini: pip uninstall opencv-python-headless -y && pip install opencv-python")
                break
                
    except KeyboardInterrupt:
        print("\n[!] Pengujian dihentikan oleh pengguna.")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[*] Kamera ditutup. Selesai.")

if __name__ == "__main__":
    test_ai_pid()
