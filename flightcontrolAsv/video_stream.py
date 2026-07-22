import os
import cv2
import time
import threading
import numpy as np
import urllib.request

class VideoStreamer:
    def __init__(self, camera_index=0, width=640, height=480, fps=15, backend_url="http://localhost:3000/api/v1/video/upload", frame_callback=None):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.backend_url = backend_url
        self.frame_callback = frame_callback
        self._is_running = False
        self._capture_thread = None

        # State Recording (Video mentah tanpa object detection)
        self.is_recording = False
        self.recording_writer = None
        self.recording_filename = None
        self.record_width = width
        self.record_height = height
        self._recording_lock = threading.Lock()

    def start_recording(self, width=None, height=None, save_dir="recordings"):
        with self._recording_lock:
            if self.is_recording:
                return self.recording_filename

            os.makedirs(save_dir, exist_ok=True)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"rec_{timestamp}.mp4"
            filepath = os.path.join(save_dir, filename)

            rec_w = width if width is not None and width > 0 else self.width
            rec_h = height if height is not None and height > 0 else self.height
            self.record_width = int(rec_w)
            self.record_height = int(rec_h)

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.recording_writer = cv2.VideoWriter(filepath, fourcc, self.fps, (self.record_width, self.record_height))

            if not self.recording_writer.isOpened():
                # Fallback if mp4v codec is not available
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                filepath = os.path.join(save_dir, f"rec_{timestamp}.avi")
                self.recording_writer = cv2.VideoWriter(filepath, fourcc, self.fps, (self.record_width, self.record_height))

            self.recording_filename = filepath
            self.is_recording = True
            print(f"[VideoStream] Recording started: {filepath} ({self.record_width}x{self.record_height})")
            return filepath

    def stop_recording(self):
        with self._recording_lock:
            if not self.is_recording:
                return None
            self.is_recording = False
            filename = self.recording_filename
            if self.recording_writer:
                self.recording_writer.release()
                self.recording_writer = None
            print(f"[VideoStream] Recording stopped: {filename}")
            return filename

    def start(self):
        if self._is_running:
            return
        self._is_running = True
        
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        print(f"[VideoStream] Started uploading frames to {self.backend_url}")

    def stop(self):
        self.stop_recording()
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

            # Record raw frame WITHOUT object detection
            if self.is_recording and self.recording_writer is not None:
                with self._recording_lock:
                    if self.is_recording and self.recording_writer is not None:
                        if frame.shape[1] != self.record_width or frame.shape[0] != self.record_height:
                            rec_frame = cv2.resize(frame, (self.record_width, self.record_height))
                        else:
                            rec_frame = frame
                        self.recording_writer.write(rec_frame)

            # Process frame with YOLO callback for live stream display
            if self.frame_callback:
                processed_frame = self.frame_callback(frame.copy())
            else:
                processed_frame = frame
                
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 60]
            result, encimg = cv2.imencode('.jpg', processed_frame, encode_param)
            
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

