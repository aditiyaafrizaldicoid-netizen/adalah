import os
import cv2
import time
import threading
import numpy as np
import numpy as np
import requests
class VideoStreamer:
    def __init__(self, camera_index=0, width=640, height=480, fps=15, backend_url="http://172.16.51.69:3000/api/v1/video/upload", frame_callback=None, flip_horizontal=False):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self.backend_url = backend_url
        self.frame_callback = frame_callback
        self.flip_horizontal = flip_horizontal
        self._is_running = False
        self._capture_thread = None
        self._upload_thread = None

        # Buffer for passing frame to upload worker thread
        self._latest_frame = None
        self._frame_lock = threading.Lock()

        # ------------------------------------------------------------------ #
        #  Streaming ON/OFF toggle                                            #
        # ------------------------------------------------------------------ #
        # is_streaming = True  → encode JPEG + upload ke backend (default ON)
        # is_streaming = False → hanya proses YOLO untuk kontrol ASV,
        #                        TIDAK encode/upload frame (hemat CPU & bandwidth)
        self.is_streaming = True
        self._streaming_lock = threading.Lock()

        # State Recording (Video mentah tanpa object detection)
        self.is_recording = False
        self.recording_writer = None
        self.recording_filename = None
        self.record_width = width
        self.record_height = height
        self.actual_camera_fps = fps
        self._recording_lock = threading.Lock()

        # Callback untuk notifikasi status kamera ke ws_client
        # Signature: callback(is_ok: bool, reason: str)
        self._status_callback = None
        self._camera_ok = None  # Status kamera saat ini (None = belum diinisialisasi)

    def set_status_callback(self, callback):
        """Daftarkan callback yang dipanggil saat status kamera berubah.
        Callback signature: callback(is_ok: bool, reason: str)
        """
        self._status_callback = callback

    def is_camera_ok(self) -> bool:
        """Mengembalikan status koneksi kamera saat ini."""
        return bool(self._camera_ok)

    # ------------------------------------------------------------------ #
    #  Streaming Toggle API                                                #
    # ------------------------------------------------------------------ #

    def start_streaming(self):
        """Aktifkan encoding + upload frame ke backend."""
        with self._streaming_lock:
            if not self.is_streaming:
                self.is_streaming = True
                print("[VideoStream] 🟢 Streaming DIAKTIFKAN (encode + upload ke backend ON)")
        return self.is_streaming

    def stop_streaming(self):
        """
        Matikan encoding + upload ke backend.
        YOLO detection & kontrol ASV tetap berjalan.
        """
        with self._streaming_lock:
            if self.is_streaming:
                self.is_streaming = False
                print("[VideoStream] 🔴 Streaming DIMATIKAN (encode + upload ke backend OFF — YOLO tetap aktif)")
        return self.is_streaming

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

            rec_fps = self.actual_camera_fps if (self.actual_camera_fps and self.actual_camera_fps > 0) else self.fps
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            self.recording_writer = cv2.VideoWriter(filepath, fourcc, rec_fps, (self.record_width, self.record_height))

            if not self.recording_writer.isOpened():
                # Fallback if mp4v codec is not available
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                filepath = os.path.join(save_dir, f"rec_{timestamp}.avi")
                self.recording_writer = cv2.VideoWriter(filepath, fourcc, rec_fps, (self.record_width, self.record_height))

            self.recording_filename = filepath
            self.is_recording = True
            print(f"[VideoStream] Recording started: {filepath} ({self.record_width}x{self.record_height} @ {rec_fps} FPS)")
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
        
        # Dedicated camera capture & recording thread (Full Speed)
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

        # Dedicated YOLO processing & HTTP upload thread (Independent Rate)
        self._upload_thread = threading.Thread(target=self._upload_loop, daemon=True)
        self._upload_thread.start()

        print(f"[VideoStream] Started camera capture & frame upload to {self.backend_url}")

    def stop(self):
        self.stop_recording()
        self._is_running = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=1.0)
        if self._upload_thread and self._upload_thread.is_alive():
            self._upload_thread.join(timeout=1.0)
            
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
        fallback_frame = self._create_fallback_frame()

        fail_count = 0
        FAIL_THRESHOLD = 15          # ~1 detik pada 15fps sebelum dianggap disconnect
        RETRY_INTERVAL = 2.0         # jeda antar percobaan reconnect
        last_retry_time = 0

        def try_open_camera():
            c = cv2.VideoCapture(self.camera_index)
            if c.isOpened():
                c.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                c.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                cam_fps = c.get(cv2.CAP_PROP_FPS)
                if cam_fps and 5 <= cam_fps <= 60:
                    self.actual_camera_fps = float(cam_fps)
                print(f"[VideoStream] Kamera {self.camera_index} berhasil (re)connect.")
            return c

        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cam_fps = cap.get(cv2.CAP_PROP_FPS)
            if cam_fps and 5 <= cam_fps <= 60:
                self.actual_camera_fps = float(cam_fps)
            print(f"[VideoStream] Kamera {self.camera_index} terbuka. FPS hardware: {self.actual_camera_fps}")
            # Kamera berhasil dibuka → notify ws_client
            self._notify_camera_status(True, "camera_opened")
        else:
            print(f"[VideoStream] Gagal membuka kamera {self.camera_index}. Menggunakan mode fallback.")
            self._notify_camera_status(False, "camera_open_failed")

        while self._is_running:
            ret = False
            frame = None

            if cap.isOpened():
                ret, frame = cap.read()

            if ret:
                fail_count = 0
                if self.flip_horizontal:
                    frame = cv2.flip(frame, 1)  # Flip horizontal hanya jika flip_horizontal=True
            else:
                fail_count += 1

                frame = fallback_frame

                # Kalau gagal beruntun melewati threshold, anggap kamera disconnect -> coba reconnect
                if fail_count >= FAIL_THRESHOLD:
                    now = time.time()
                    if now - last_retry_time >= RETRY_INTERVAL:
                        last_retry_time = now
                        print("[VideoStream] Kamera terdeteksi disconnect, mencoba reconnect...")
                        # Notify ws_client bahwa kamera putus
                        self._notify_camera_status(False, "camera_disconnect_detected")
                        try:
                            cap.release()
                        except Exception:
                            pass
                        cap = try_open_camera()
                        if cap.isOpened():
                            fail_count = 0
                            # Notify ws_client bahwa kamera kembali terhubung
                            self._notify_camera_status(True, "camera_reconnected")
                    else:
                        time.sleep(1.0 / self.fps)

            if frame.shape[1] != self.width or frame.shape[0] != self.height:
                frame = cv2.resize(frame, (self.width, self.height))

            # 1. Record raw frame WITHOUT object detection (FULL SPEED, NO DELAY)
            if self.is_recording and self.recording_writer is not None:
                with self._recording_lock:
                    if self.is_recording and self.recording_writer is not None:
                        if frame.shape[1] != self.record_width or frame.shape[0] != self.record_height:
                            rec_frame = cv2.resize(frame, (self.record_width, self.record_height))
                        else:
                            rec_frame = frame
                        self.recording_writer.write(rec_frame)

            # 2. Save latest frame for upload thread
            with self._frame_lock:
                self._latest_frame = frame

        if cap.isOpened():
            cap.release()

    def _notify_camera_status(self, is_ok: bool, reason: str = ""):
        """
        Helper internal: panggil callback status kamera hanya jika status benar-benar berubah.
        Thread-safe karena GIL Python melindungi assignment boolean.
        """
        if is_ok == self._camera_ok:
            return  # Status tidak berubah, abaikan
        self._camera_ok = is_ok
        if self._status_callback:
            try:
                self._status_callback(is_ok, reason)
            except Exception as e:
                print(f"[VideoStream] Error in status callback: {e}")

    def _upload_loop(self):
        while self._is_running:
            frame = None
            with self._frame_lock:
                if self._latest_frame is not None:
                    frame = self._latest_frame.copy()

            if frame is not None:
                # --------------------------------------------------------
                # 1. Selalu jalankan YOLO callback agar kontrol ASV tetap
                #    berjalan meskipun streaming dimatikan.
                # --------------------------------------------------------
                if self.frame_callback:
                    processed_frame = self.frame_callback(frame)
                else:
                    processed_frame = frame

                # --------------------------------------------------------
                # 2. Encode + upload ke backend HANYA jika streaming ON.
                #    Ketika streaming OFF: skip encode JPEG & HTTP POST
                #    → hemat CPU (encode) + bandwidth (upload).
                # --------------------------------------------------------
                with self._streaming_lock:
                    streaming_active = self.is_streaming

                if streaming_active:
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 60]
                    result, encimg = cv2.imencode('.jpg', processed_frame, encode_param)
                    if result:
                        try:
                            files = {'frame': ('frame.jpg', encimg.tobytes(), 'image/jpeg')}
                            if not hasattr(self, 'session'):
                                self.session = requests.Session()
                            response = self.session.post(self.backend_url, files=files, timeout=(1.0, 2.0))
                            if response.status_code != 200:
                                print(f"[VideoStream] Backend error: {response.status_code} - {response.text}")
                        except Exception as e:
                            print(f"[VideoStream] Upload error: {e}")

            time.sleep(1.0 / self.fps)


