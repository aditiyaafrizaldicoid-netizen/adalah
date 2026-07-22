import cv2
from ultralytics import YOLO

class BallTracker:
    def __init__(self, model_path="yolov8n.pt", target_class=32, conf_threshold=0.5):
        """
        Initializes the YOLOv8 ball tracker.
        :param model_path: Path to the YOLOv8 model weights (default yolov8n.pt will be downloaded).
        :param target_class: Class ID for the target object (32 is 'sports ball' in COCO).
        :param conf_threshold: Confidence threshold for detection.
        """
        print(f"[BallTracker] Loading YOLO model from {model_path}...")
        self.model = YOLO(model_path)
        self.target_class = target_class
        self.conf_threshold = conf_threshold
        print("[BallTracker] Model loaded successfully.")

    def process_frame(self, frame):
        """
        Processes a single frame, detects the ball, and draws a bounding box.
        :param frame: The BGR image frame from OpenCV.
        :return: (processed_frame, ball_center_x, ball_center_y)
                 If no ball is detected, center coordinates will be None.
        """
        results = self.model(frame, stream=True, verbose=False)
        
        detected_centers_x = []
        detected_centers_y = []

        for result in results:
            boxes = result.boxes
            for box in boxes:
                cls = int(box.cls[0])
                conf = float(box.conf[0])
                
                # Check if detected object is the target class and above confidence threshold
                is_target = False
                if self.target_class is None:
                    is_target = True
                elif isinstance(self.target_class, (list, tuple)) and cls in self.target_class:
                    is_target = True
                elif cls == self.target_class:
                    is_target = True

                if is_target and conf > self.conf_threshold:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    
                    detected_centers_x.append(center_x)
                    detected_centers_y.append(center_y)
                    
                    # Warna kotak (otomatis: merah jika class 1, hijau jika class 0)
                    color = (0, 0, 255) if cls == 1 else (0, 255, 0)
                    
                    # Draw bounding box
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    
                    # Draw center point of this ball
                    cv2.circle(frame, (center_x, center_y), 5, (255, 255, 0), -1)
                    
                    # Draw label
                    class_name = self.model.names[cls] if hasattr(self.model, 'names') else str(cls)
                    label = f"{class_name}: {conf:.2f}"
                    cv2.putText(frame, label, (x1, max(y1 - 10, 0)), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # Menghitung titik target PID (rata-rata dari semua bola yang dideteksi)
        # Jika hanya 1 bola, PID akan mengejar bola itu.
        # Jika ada 2 bola (gerbang hijau & merah), PID akan mengejar titik tengah di antara keduanya!
        avg_center_x = sum(detected_centers_x) // len(detected_centers_x) if detected_centers_x else None
        avg_center_y = sum(detected_centers_y) // len(detected_centers_y) if detected_centers_y else None
        
        # Gambar indikator target PID (titik ungu) jika ada lebih dari 1 bola
        if avg_center_x is not None and len(detected_centers_x) > 1:
            cv2.circle(frame, (avg_center_x, avg_center_y), 8, (255, 0, 255), -1)
            cv2.putText(frame, "PID TARGET", (avg_center_x - 35, max(avg_center_y - 15, 0)), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)
                        
        return frame, avg_center_x, avg_center_y
