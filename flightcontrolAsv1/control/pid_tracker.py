from simple_pid import PID


class TrackingController:
    """
    Kontroler Tracking Super Sederhana (Tanpa FSM State Machine).
    Murni & langsung mengonversi posisi objek (gate_center_x) menjadi turn_rate dan forward_speed.

    Anti-windup: integrator di-reset saat error berganti tanda (zero-crossing),
    mencegah overshooting akibat integral yang terakumulasi terlalu besar.
    """

    def __init__(self, frame_width=1920, kp=1.0, ki=0.0, kd=0.0,
                 forward_speed=0.2, max_turn_rate=20.0, **kwargs):
        self.frame_width = frame_width
        self.center_x = frame_width // 2
        self.forward_speed = forward_speed
        self.max_turn_rate = max_turn_rate

        # Dead-zone: error di bawah nilai ini dianggap "lurus" (tidak ada steering output).
        # Mencegah micro-correction flicker yang membuat kapal bergetar saat hampir lurus.
        # 45px @ 1920px frame width (dulu 15px @ 640px) — diskalakan 3x mengikuti
        # kenaikan resolusi kamera (Logitech MX Brio, 1920x1080) agar dead-zone
        # relatif terhadap lebar frame tetap sama (~2.3%).
        self.align_threshold_px: float = 45.0

        # PID Sederhana: error_px (pixel) -> output = turn_rate deg/s
        self.pid = PID(kp, ki, kd, setpoint=0.0)
        self.pid.output_limits = (-self.max_turn_rate, self.max_turn_rate)

        # Simpan tanda error sebelumnya untuk deteksi zero-crossing (anti-windup)
        self._last_error_sign: float = 0.0

    def reset(self):
        self.pid.reset()
        self._last_error_sign = 0.0
        print("[TrackingController] 🔄 Reset PID tracker.")

    def update_pid_params(self, kp=None, ki=None, kd=None, forward_speed=None, max_turn_rate=None, align_threshold_px=None, **kwargs):
        if kp is not None:
            self.pid.Kp = float(kp)
        if ki is not None:
            self.pid.Ki = float(ki)
        if kd is not None:
            self.pid.Kd = float(kd)
        if forward_speed is not None:
            self.forward_speed = float(forward_speed)
        if max_turn_rate is not None:
            self.max_turn_rate = max(5.0, min(60.0, float(max_turn_rate)))
            self.pid.output_limits = (-self.max_turn_rate, self.max_turn_rate)
        if align_threshold_px is not None:
            self.align_threshold_px = max(0.0, float(align_threshold_px))
        print(f"[TrackingController] PID Updated -> Kp:{self.pid.Kp}, Ki:{self.pid.Ki}, Kd:{self.pid.Kd}, Speed:{self.forward_speed}m/s, MaxTurn:{self.max_turn_rate}deg/s")

    def _check_and_reset_windup(self, error_px: float):
        """
        Anti-windup: reset HANYA komponen integral PID saat error berganti tanda (zero-crossing).
        Hanya integral (_integral) yang di-reset — bukan seluruh PID state — agar:
        - Respons proporsional tetap aktif secara instan (tidak ada "silent frame")
        - Derivative history tetap terjaga agar tidak spike saat zero-crossing
        - Mencegah integral yang terakumulasi mendorong kapal ke arah yang salah
        """
        current_sign = 1.0 if error_px > 0 else (-1.0 if error_px < 0 else 0.0)
        if (self._last_error_sign != 0.0
                and current_sign != 0.0
                and current_sign != self._last_error_sign):
            # Error berganti tanda → reset HANYA integrator, bukan seluruh PID
            # simple_pid menyimpan integral di atribut _integral
            if hasattr(self.pid, '_integral'):
                self.pid._integral = 0.0
        if current_sign != 0.0:
            self._last_error_sign = current_sign

    def compute_velocity(self, gate_center_x):
        """
        Hitung kecepatan & belokan langsung tanpa FSM state machine.
        - Objek terdeteksi -> Maju forward_speed, Belok PID(error_px).
        - Objek tidak ada  -> Maju 0.0, Belok 0.0.
        """
        # Hitung error piksel dari tengah frame.
        # simple_pid menghitung: output = Kp × (setpoint − measurement) = −Kp × measurement
        # Agar output POSITIF saat gate di KANAN (Belok Kanan) dan
        # NEGATIF saat gate di KIRI (Belok Kiri), kita balik tanda:
        #   error_px = center_x − gate_center_x
        #   gate di kanan (gate_x > center) → error_px < 0 → output = −Kp×(−|e|) = +|e| ✓
        #   gate di kiri  (gate_x < center) → error_px > 0 → output = −Kp×(+|e|) = −|e| ✓
        error_px = float(self.center_x - gate_center_x)

        # Dead-zone: error kecil di bawah threshold → anggap lurus, tidak ada koreksi
        if abs(error_px) < self.align_threshold_px:
            return self.forward_speed, 0.0, "TRACKING"

        # Anti-windup: reset integrator jika error berganti arah
        self._check_and_reset_windup(error_px)

        turn_rate = float(self.pid(error_px))

        # Mengembalikan kecepatan maju & belokan presisi
        return self.forward_speed, turn_rate, "TRACKING"

    def compute_normalized_steering(self, gate_center_x) -> float:
        """
        Hitung nilai steering ter-normalisasi (-1.0 s/d +1.0) untuk MANUAL Mode RC Override.
        -1.0 = Belok Kiri Penuh (PWM 1000us)
         0.0 = Lurus Presisi (PWM 1500us)
        +1.0 = Belok Kanan Penuh (PWM 2000us)
        """
        if gate_center_x is None:
            return 0.0

        # Balik tanda error agar output PID sesuai arah fisik kamera non-mirror:
        #   gate di kanan (gate_x > center) → error_px < 0 → output positif → steer kanan (+1.0) ✓
        #   gate di kiri  (gate_x < center) → error_px > 0 → output negatif → steer kiri  (-1.0) ✓
        error_px = float(self.center_x - gate_center_x)

        # Dead-zone: error kecil dianggap lurus — tidak ada micro-correction
        if abs(error_px) < self.align_threshold_px:
            return 0.0

        # Anti-windup: reset integrator jika error berganti arah
        self._check_and_reset_windup(error_px)

        raw_output = float(self.pid(error_px))

        # Normalisasi output dari range [-max_turn_rate, +max_turn_rate] ke [-1.0, +1.0]
        steering_norm = raw_output / self.max_turn_rate if self.max_turn_rate > 0 else 0.0
        return max(-1.0, min(1.0, steering_norm))
