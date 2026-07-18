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
    baudrate = 115200
    
    asv = ASVController(port=port, baudrate=baudrate)
    asv.start()
    
    ws_url = os.getenv("ASV_WS_URL", "ws://localhost:3000/api/v1/ws/asv")
    ws_client = ASVWebSocketClient(asv, ws_url=ws_url)
    ws_client.start()
    
    # 3. Setup Video Streamer (Pushing to Backend)
    # video_upload_url = os.getenv("ASV_VIDEO_URL", "http://localhost:3000/api/v1/video/upload")
    # video_streamer = VideoStreamer(camera_index=0, width=640, height=480, fps=15, backend_url=video_upload_url)
    # video_streamer.start()
    
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
