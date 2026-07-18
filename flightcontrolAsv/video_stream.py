import cv2
import time
import threading
import numpy as np
import urllib.request

class VideoStreamer:
    def __init__(self, camera_index=0, width=640, height=480, fps=15, backend_url="http://localhost:3000/api/v1/video/upload"):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.backend_url = backend_url
        self._is_running = False
        self._capture_thread = None

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        print(f"[VideoStream] Started uploading frames to {self.backend_url}")

    def stop(self):
        self._is_running = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=1.0)
            
    def _create_fallback_frame(self):
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        text = "NO CAMERA DETECTED"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        color = (0, 0, 255) # Red
        thickness = 2
        
        text_size = cv2.getTextSize(text, font, font_scale, thickness)[0]
        text_x = (self.width - text_size[0]) // 2
        text_y = (self.height + text_size[1]) // 2
        
        cv2.putText(frame, text, (text_x, text_y), font, font_scale, color, thickness)
        return frame
        
    def _capture_loop(self):
        print(f"[VideoStream] Mencoba membuka kamera index {self.camera_index}...")
        cap = cv2.VideoCapture(self.camera_index)
        
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            print(f"[VideoStream] Kamera {self.camera_index} terbuka.")
        else:
            print(f"[VideoStream] Gagal membuka kamera {self.camera_index}. Menggunakan mode fallback.")
            
        fallback_frame = self._create_fallback_frame()

        while self._is_running:
            if cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    frame = fallback_frame
            else:
                frame = fallback_frame
                
            if frame.shape[1] != self.width or frame.shape[0] != self.height:
                frame = cv2.resize(frame, (self.width, self.height))
                
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 60]
            result, encimg = cv2.imencode('.jpg', frame, encode_param)
            
            if result:
                try:
                    req = urllib.request.Request(
                        self.backend_url,
                        data=encimg.tobytes(),
                        headers={'Content-Type': 'image/jpeg'},
                        method='POST'
                    )
                    with urllib.request.urlopen(req, timeout=0.5) as response:
                        pass
                except Exception as e:
                    pass
                    
            time.sleep(1.0 / self.fps)
            
        if cap.isOpened():
            cap.release()
