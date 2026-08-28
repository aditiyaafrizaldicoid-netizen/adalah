import cv2
from ultralytics import YOLO

from vision.gate_convention import virtual_gate_center_x


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

    # Lebar SETENGAH gerbang yang diasumsikan saat hanya SATU bola yang terlihat,
    # sebagai rasio terhadap lebar frame. Dipakai untuk memproyeksikan titik tengah
    # gerbang dari satu bola (lihat gate_convention.virtual_gate_center_x).
    SINGLE_BALL_HALF_GATE_RATIO = 0.2

    # Warna OSD untuk setiap gate state
    _GATE_STATE_COLORS = {
        "SEARCHING":    (180, 180, 180),  # abu-abu
        "LOCKED":       (0, 255, 100),    # hijau terang
        "TRANSITIONING":(0, 200, 255),    # kuning-cyan
        "CLEARED":      (255, 80, 255),   # magenta
    }

    def __init__(self, model_path="yolov8n.pt", target_class=32, conf_threshold=0.5,
                 min_detection_area_px2=4000, **kwargs):
        """
        :param model_path:    Path ke file bobot YOLO.
        :param target_class:  Class ID target, atau list class ID (misal [0, 1] untuk gate hijau+merah).
        :param conf_threshold: Confidence threshold deteksi minimum.
        :param min_detection_area_px2: Area bounding box (piksel²) minimum agar sebuah
            deteksi dianggap valid. Deteksi di bawah ini dibuang di SUMBER (sebelum masuk
            detected_balls/gate_x sama sekali) — noise-floor kamera yang berlaku untuk
            SEMUA mission step (TRACKING_BUOY, SEQUENTIAL_BUOY, GYRO_FORWARD), bukan
            per-step seperti ignore_area_px2 di mission_engine.py. Live-tunable dari
            Calibration → Vision/Camera di base station (lihat set_min_detection_area()),
            disimpan di DB via /api/v1/pid-config. Default 4000px² @ 1920x1080
            (kamera Logitech MX Brio).
        """
        print(f"[BallTracker] Loading YOLO model from {model_path}...")
        self.model = YOLO(model_path)
        self.target_class = target_class
        self.conf_threshold = conf_threshold
        self.min_detection_area_px2 = float(min_detection_area_px2)
        print("[BallTracker] Model loaded successfully.")

    def set_min_detection_area(self, px2: float):
        """Update noise-floor deteksi secara live (dipanggil dari WS/REST config fetch)."""
        try:
            self.min_detection_area_px2 = max(0.0, float(px2))
            print(f"[BallTracker] Min detection area updated -> {self.min_detection_area_px2:.0f}px²")
        except (TypeError, ValueError):
            pass

    def process_frame(self, frame, state_label: str = None, gate_state: str = None):
        """
        Mendeteksi bola hijau & merah, menggambar anotasi gate, dan mengembalikan
        koordinat midpoint gate serta dictionary bola yang terdeteksi.

        Returns:
            (processed_frame, gate_center_x, gate_center_y, detected_balls)

            detected_balls: dict dengan key "red" dan "green", masing-masing berisi
            list tuple (cx, cy, x1, y1, x2, y2) dari bola yang terdeteksi.
            Contoh: {"red": [(cx, cy, x1, y1, x2, y2), ...], "green": [...]}

        CATATAN: Kalkulasi gate_center_x/gate_center_y di sini hanya digunakan
        sebagai fallback visual. MissionEngine yang memegang Gate State Machine
        yang menjadi sumber kebenaran untuk navigasi.
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

                # Noise-floor: buang deteksi yang bounding box-nya lebih kecil dari
                # min_detection_area_px2 SEBELUM masuk ke green_balls/red_balls atau
                # gate_x fallback — berlaku di sumber untuk semua mission step.
                if (x2 - x1) * (y2 - y1) < self.min_detection_area_px2:
                    continue

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

        # ---- Hitung midpoint gate murni (hanya untuk fallback visual) ----
        gate_center_x = None
        gate_center_y = None

        # Prioritaskan bola dengan area terbesar (paling dekat ke kamera secara fisik)
        sorted_red = sorted(red_balls, key=lambda b: (b[4] - b[2]) * (b[5] - b[3]), reverse=True)
        sorted_green = sorted(green_balls, key=lambda b: (b[4] - b[2]) * (b[5] - b[3]), reverse=True)

        if len(sorted_red) > 0 and len(sorted_green) > 0:
            # Pasangan bola merah & hijau TERDEKAT di depan kapal. Midpoint dua
            # bola tidak bergantung pada bola mana yang di kiri/kanan, jadi blok ini
            # aman terhadap konvensi sisi mana pun (lihat vision/gate_convention.py).
            closest_red = sorted_red[0]
            closest_green = sorted_green[0]
            red_pt = (closest_red[0], closest_red[1])
            green_pt = (closest_green[0], closest_green[1])

            gate_center_x = (red_pt[0] + green_pt[0]) // 2
            gate_center_y = (red_pt[1] + green_pt[1]) // 2

            # Gambar garis gate penghubung pasangan terdekat
            cv2.line(frame, red_pt, green_pt, self.COLOR_GATE_LINE, 2, cv2.LINE_AA)

        elif len(sorted_green) > 0 and len(sorted_red) == 0:
            # Hanya bola HIJAU terdeteksi. Arah offset ditentukan MURNI oleh warna
            # bola (hijau = penanda tepi KIRI → lintasan ada di KANAN-nya), BUKAN
            # oleh posisi bola relatif terhadap garis tengah frame.
            g = sorted_green[0]
            gate_center_x = int(round(virtual_gate_center_x(
                g[0], "green", w * self.SINGLE_BALL_HALF_GATE_RATIO)))
            gate_center_y = g[1]

        elif len(sorted_red) > 0 and len(sorted_green) == 0:
            # Hanya bola MERAH terdeteksi (penanda tepi KANAN → lintasan di KIRI-nya).
            r = sorted_red[0]
            gate_center_x = int(round(virtual_gate_center_x(
                r[0], "red", w * self.SINGLE_BALL_HALF_GATE_RATIO)))
            gate_center_y = r[1]

        elif len(all_centers_x) >= 2:
            gate_center_x = sum(all_centers_x) // len(all_centers_x)
            gate_center_y = sum(all_centers_y) // len(all_centers_y)

        if gate_center_x is not None:
            # Titik tengah gerbang BOLEH berada di luar frame saat hanya satu bola
            # terlihat (bola pasangannya memang sudah keluar frame) — nilai yang
            # DIKEMBALIKAN sengaja tidak di-clamp supaya error piksel tetap kontinu
            # dan proporsional. Yang di-clamp hanya koordinat GAMBAR, supaya penanda
            # OSD-nya tetap kelihatan menempel di tepi frame.
            draw_x = max(0, min(w - 1, gate_center_x))
            draw_y = max(0, min(h - 1, gate_center_y))
            off_screen = draw_x != gate_center_x

            cv2.circle(frame, (draw_x, draw_y), 10, self.COLOR_MIDPOINT, -1)
            cv2.circle(frame, (draw_x, draw_y), 14, self.COLOR_MIDPOINT, 2)
            mid_label = "GATE MID (luar frame)" if off_screen else "GATE MID"
            cv2.putText(frame, mid_label, (max(draw_x - 40, 0), max(draw_y - 18, 0)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, self.COLOR_MIDPOINT, 2)

            # Gambar garis error dari tengah frame ke midpoint gate
            error_px = gate_center_x - frame_center_x
            cv2.line(frame, (frame_center_x, draw_y), (draw_x, draw_y),
                     self.COLOR_ERROR_LINE, 2, cv2.LINE_AA)
            cv2.putText(frame, f"err:{error_px:+d}px",
                        (min(frame_center_x, draw_x), max(draw_y - 8, 0)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, self.COLOR_ERROR_LINE, 1)

        # ---- OSD: State label (mission step) ----
        osd_y = 8
        if state_label:
            cv2.rectangle(frame, (8, osd_y), (260, osd_y + 30), (0, 0, 0), -1)
            cv2.putText(frame, f"STATE: {state_label}", (12, osd_y + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)
            osd_y += 36

        # ---- OSD: Gate State Machine label ----
        if gate_state:
            gate_color = self._GATE_STATE_COLORS.get(gate_state, (255, 255, 255))
            cv2.rectangle(frame, (8, osd_y), (280, osd_y + 30), (0, 0, 0), -1)
            cv2.putText(frame, f"GATE: {gate_state}", (12, osd_y + 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, gate_color, 2)

        # ---- Return: frame, midpoint xy, detected balls per class ----
        detected_balls = {
            "red":   sorted_red,    # list (cx, cy, x1, y1, x2, y2), sorted foreground-first
            "green": sorted_green,  # list (cx, cy, x1, y1, x2, y2), sorted foreground-first
        }
        return frame, gate_center_x, gate_center_y, detected_balls
