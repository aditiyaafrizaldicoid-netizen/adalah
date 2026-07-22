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
    
    ws_url = os.getenv("ASV_WS_URL", "ws://localhost:3000/api/v1/ws/asv")
    ws_client = ASVWebSocketClient(asv, ws_url=ws_url)
    ws_client.start()
    
    # Initialize YOLO Tracker and PID Controller
    from vision.tracker import BallTracker
    from control.pid_tracker import TrackingController
    
    # We use the same width as the video stream
    camera_width = 640
    tracker = BallTracker(model_path="best.pt", target_class=[0, 1], conf_threshold=0.6)
    controller = TrackingController(frame_width=camera_width, kp=0.4, ki=0.0, kd=0.1)
    
    def process_and_control(frame):
        processed_frame, ball_x, ball_y = tracker.process_frame(frame)
        
        # Only compute steering if ASV is connected
        if asv.is_connected():
            steering_pwm, is_tracking = controller.compute_steering(ball_x)
            
            if is_tracking:
                # Channel 1 is typically steering. We send [steering_pwm, 65535, 65535, ...]
                # to only override steering.
                channels = [steering_pwm, 65535, 65535, 65535]
                asv.send_rc_override(channels)
            else:
                # If no ball, optionally stop steering override or return to center
                asv.send_rc_override([1500, 65535, 65535, 65535])
                
        return processed_frame

    # 3. Setup Video Streamer (Pushing to Backend)
    video_upload_url = os.getenv("ASV_VIDEO_URL", "http://localhost:3000/api/v1/video/upload")
    video_streamer = VideoStreamer(camera_index=2, width=camera_width, height=640, fps=30, backend_url=video_upload_url, frame_callback=process_and_control)
    video_streamer.start()
    
    try:
        print("\n[Main] Sistem berjalan. Tekan Ctrl+C untuk berhenti.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Main] Dibatalkan oleh pengguna.")
    finally:
        # video_streamer.stop()
        ws_client.stop()
        asv.stop()
        print("\n[Main] Selesai. Semua koneksi ditutup.")

if __name__ == "__main__":
    main()
