import cv2
from ultralytics import YOLO

from vision.ball_pairing import sort_ball_pairs


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
    COLOR_BALL_NUMBER_TEXT = (255, 255, 255)  # Teks nomor bola (putih)

    # Rasio area minimum antara bola merah & hijau agar dianggap SATU pasangan valid
    # untuk penomoran (1,2,3,4,...). Harus SAMA dengan MissionEngine.SEQ_PAIR_AREA_RATIO_MIN
    # agar nomor yang ditampilkan di video 1:1 dengan pasangan yang benar-benar dipakai
    # untuk navigasi — lihat vision/ball_pairing.py.
    BALL_PAIR_MIN_AREA_RATIO = 0.35

    # Warna OSD untuk setiap gate state
    _GATE_STATE_COLORS = {
        "SEARCHING":    (180, 180, 180),  # abu-abu
        "LOCKED":       (0, 255, 100),    # hijau terang
        "TRANSITIONING":(0, 200, 255),    # kuning-cyan
        "CLEARED":      (255, 80, 255),   # magenta
    }

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

        # ---- Penomoran pasangan bola (1, 2, 3, 4, ...) di atas bounding box ----
        # Dipakai operator untuk verifikasi VISUAL bahwa sistem memasangkan bola yang
        # BENAR untuk hitung titik tengah (center point) navigasi — supaya kapal tidak
        # salah arah akibat pasangan yang keliru (mis. bola sisa gate 1 kepasang dengan
        # bola gate 2). Bola 1 & 2 = pasangan (gate) terdekat, bola 3 & 4 = pasangan
        # berikutnya, dst. Urutan & aturan pairing-nya SAMA PERSIS dengan yang dipakai
        # MissionEngine untuk SEQUENTIAL_BUOY (vision/ball_pairing.sort_ball_pairs) —
        # hanya bola yang benar-benar membentuk pasangan valid yang diberi nomor; bola
        # tanpa pasangan (mis. hanya 1 warna terdeteksi) tidak dinomori.
        numbered_pairs = sort_ball_pairs(
            red_balls, green_balls,
            min_area_ratio=self.BALL_PAIR_MIN_AREA_RATIO, max_pairs=3
        )
        for pair_idx, (red_ball, green_ball) in enumerate(numbered_pairs):
            self._draw_ball_number(frame, red_ball,   pair_idx * 2 + 1, self.COLOR_RED_BALL)
            self._draw_ball_number(frame, green_ball, pair_idx * 2 + 2, self.COLOR_GREEN_BALL)

        # ---- Hitung midpoint gate murni (hanya untuk fallback visual) ----
        gate_center_x = None
        gate_center_y = None

        # Prioritaskan bola dengan area terbesar (paling dekat ke kamera secara fisik)
        sorted_red = sorted(red_balls, key=lambda b: (b[4] - b[2]) * (b[5] - b[3]), reverse=True)
        sorted_green = sorted(green_balls, key=lambda b: (b[4] - b[2]) * (b[5] - b[3]), reverse=True)

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
            # Hanya bola hijau terdeteksi → offset target ke kiri (-120px)
            g = sorted_green[0]
            offset_px = int(w * 0.2)
            gate_center_x = max(0, g[0] - offset_px)
            gate_center_y = g[1]

        elif len(sorted_red) > 0 and len(sorted_green) == 0:
            # Hanya bola merah terdeteksi → offset target ke kanan (+120px)
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

    @classmethod
    def _draw_ball_number(cls, frame, ball, number: int, color):
        """
        Gambar badge nomor (angka besar dengan latar warna solid) TEPAT DI ATAS
        bounding box sebuah bola — dipakai untuk penomoran pasangan (1,2,3,4,...).

        :param ball:  Tuple (cx, cy, x1, y1, x2, y2) dari bola yang akan diberi nomor.
        :param number: Nomor urut bola (1-indexed).
        :param color:  Warna latar badge (BGR) — dipakai warna kelas bola (merah/hijau)
                        agar mudah dibedakan dari label "class conf" yang sudah ada.
        """
        _cx, _cy, x1, y1, x2, y2 = ball
        text = str(number)
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.9
        thickness = 2

        (text_w, text_h), _ = cv2.getTextSize(text, font, font_scale, thickness)
        badge_h = text_h + 12
        badge_w = text_w + 16

        # Posisikan badge tepat di atas box, dengan sedikit gap. Jika box terlalu
        # dekat ke tepi atas frame, badge digeser turun agar tidak terpotong.
        badge_bottom = max(y1 - 4, badge_h)
        badge_top = badge_bottom - badge_h
        badge_left = x1
        badge_right = x1 + badge_w

        cv2.rectangle(frame, (badge_left, badge_top), (badge_right, badge_bottom), color, -1)
        cv2.putText(frame, text, (badge_left + 8, badge_bottom - 6),
                    font, font_scale, cls.COLOR_BALL_NUMBER_TEXT, thickness, cv2.LINE_AA)
