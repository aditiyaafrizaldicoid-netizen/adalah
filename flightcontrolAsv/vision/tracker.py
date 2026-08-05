import cv2
from ultralytics import YOLO


class BallTracker:
    """
    YOLO-based detector untuk bola hijau (class 0) dan bola merah (class 1)
    yang membentuk gerbang (gate) yang harus dilewati ASV dari tengah.
    """

    # Warna BGR untuk visualisasi
    COLOR_GREEN_BALL  = (0, 220, 0)      # Bola hijau (class 0)
    COLOR_RED_BALL    = (0, 0, 220)      # Bola merah (class 1)
    COLOR_GATE_LINE   = (0, 255, 255)    # Garis penghubung antar bola gate (kuning)
    COLOR_MIDPOINT    = (255, 0, 255)    # Titik tengah gate (magenta)
    COLOR_CENTER_LINE = (80, 80, 80)     # Garis tengah frame (abu-abu)
    COLOR_ERROR_LINE  = (255, 128, 0)    # Garis error (oranye)

    def __init__(self, model_path="yolov8n.pt", target_class=32, conf_threshold=0.5, **kwargs):
        """
        :param model_path:    Path ke file bobot YOLO.
        :param target_class:  Class ID target, atau list class ID (misal [0, 1] untuk gate hijau+merah).
        :param conf_threshold: Confidence threshold deteksi minimum.
        """
        print(f"[BallTracker] Loading YOLO model from {model_path}...")
        self.model = YOLO(model_path)
        self.target_class = target_class
        self.conf_threshold = conf_threshold
        print("[BallTracker] Model loaded successfully.")

    def process_frame(self, frame, state_label: str = None):
        """
        Mendeteksi bola hijau & merah, menggambar anotasi gate, dan mengembalikan
        koordinat midpoint gate secara langsung.
        """
        h, w = frame.shape[:2]
        frame_center_x = w // 2

        # Gambar garis tengah frame (referensi)
        cv2.line(frame, (frame_center_x, 0), (frame_center_x, h),
                 self.COLOR_CENTER_LINE, 1, cv2.LINE_AA)

        results = self.model(frame, stream=True, verbose=False)

        # Kumpulkan deteksi per class
        green_balls = []   # class 0
        red_balls   = []   # class 1
        all_centers_x = []
        all_centers_y = []

        for result in results:
            for box in result.boxes:
                cls  = int(box.cls[0])
                conf = float(box.conf[0])

                # Cek apakah class ini adalah target
                is_target = False
                if self.target_class is None:
                    is_target = True
                elif isinstance(self.target_class, (list, tuple)) and cls in self.target_class:
                    is_target = True
                elif cls == self.target_class:
                    is_target = True

                if not is_target or conf < self.conf_threshold:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cx = (x1 + x2) // 2
                cy = (y1 + y2) // 2

                if cls == 0:   # hijau
                    color = self.COLOR_GREEN_BALL
                    green_balls.append((cx, cy, x1, y1, x2, y2))
                else:          # merah
                    color = self.COLOR_RED_BALL
                    red_balls.append((cx, cy, x1, y1, x2, y2))

                all_centers_x.append(cx)
                all_centers_y.append(cy)

                class_name = self.model.names[cls] if hasattr(self.model, 'names') else str(cls)
                label = f"{class_name} {conf:.2f}"

                # Bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                # Center dot
                cv2.circle(frame, (cx, cy), 6, color, -1)
                # Label
                cv2.putText(frame, label, (x1, max(y1 - 10, 0)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # ---- Hitung midpoint gate murni ----
        gate_center_x = None
        gate_center_y = None

        # Prioritaskan bola terdekat dengan kamera di foreground (Kombinasi Luas Box x Posisi Y)
        sorted_red = sorted(red_balls, key=lambda b: ((b[4] - b[2]) * (b[5] - b[3])) * (b[1] ** 0.5), reverse=True)
        sorted_green = sorted(green_balls, key=lambda b: ((b[4] - b[2]) * (b[5] - b[3])) * (b[1] ** 0.5), reverse=True)

        if len(sorted_red) > 0 and len(sorted_green) > 0:
            # Pasangan bola merah (kiri) & hijau (kanan) TERDEKAT di depan kapal
            closest_red = sorted_red[0]
            closest_green = sorted_green[0]
            red_pt = (closest_red[0], closest_red[1])
            green_pt = (closest_green[0], closest_green[1])

            gate_center_x = (red_pt[0] + green_pt[0]) // 2
            gate_center_y = (red_pt[1] + green_pt[1]) // 2

            # Gambar garis gate penghubung pasangan terdekat
            cv2.line(frame, red_pt, green_pt, self.COLOR_GATE_LINE, 2, cv2.LINE_AA)

        elif len(sorted_green) > 0 and len(sorted_red) == 0:
            # Hanya bola hijau terdeteksi -> offset target ke kiri (-120px)
            g = sorted_green[0]
            offset_px = int(w * 0.2)
            gate_center_x = max(0, g[0] - offset_px)
            gate_center_y = g[1]

        elif len(sorted_red) > 0 and len(sorted_green) == 0:
            # Hanya bola merah terdeteksi -> offset target ke kanan (+120px)
            r = sorted_red[0]
            offset_px = int(w * 0.2)
            gate_center_x = min(w, r[0] + offset_px)
            gate_center_y = r[1]

        elif len(all_centers_x) >= 2:
            gate_center_x = sum(all_centers_x) // len(all_centers_x)
            gate_center_y = sum(all_centers_y) // len(all_centers_y)

        if gate_center_x is not None:
            # Gambar midpoint gate (magenta)
            cv2.circle(frame, (gate_center_x, gate_center_y), 10, self.COLOR_MIDPOINT, -1)
            cv2.circle(frame, (gate_center_x, gate_center_y), 14, self.COLOR_MIDPOINT, 2)
            cv2.putText(frame, "GATE MID", (gate_center_x - 40, max(gate_center_y - 18, 0)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.COLOR_MIDPOINT, 2)

            # Gambar garis error dari tengah frame ke midpoint gate
            error_px = gate_center_x - frame_center_x
            cv2.line(frame, (frame_center_x, gate_center_y), (gate_center_x, gate_center_y),
                     self.COLOR_ERROR_LINE, 2, cv2.LINE_AA)
            cv2.putText(frame, f"err:{error_px:+d}px",
                        (min(frame_center_x, gate_center_x), gate_center_y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, self.COLOR_ERROR_LINE, 1)

        # ---- OSD: State label ----
        if state_label:
            cv2.rectangle(frame, (8, 8), (220, 38), (0, 0, 0), -1)
            cv2.putText(frame, f"STATE: {state_label}", (12, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

        return frame, gate_center_x, gate_center_y
