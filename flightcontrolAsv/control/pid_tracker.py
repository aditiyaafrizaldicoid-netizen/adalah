from simple_pid import PID


class TrackingController:
    """
    Kontroler Tracking Super Sederhana (Tanpa FSM State Machine).
    Murni & langsung mengonversi posisi objek (gate_center_x) menjadi turn_rate dan forward_speed.
    """

    def __init__(self, frame_width=640, kp=1.0, ki=0.0, kd=0.0,
                 forward_speed=0.2, max_turn_rate=20.0, **kwargs):
        self.frame_width = frame_width
        self.center_x = frame_width // 2
        self.forward_speed = forward_speed
        self.max_turn_rate = max_turn_rate

        # PID Sederhana: error_px (pixel) -> output = turn_rate deg/s
        self.pid = PID(kp, ki, kd, setpoint=0.0)
        self.pid.output_limits = (-self.max_turn_rate, self.max_turn_rate)

    def reset(self):
        self.pid.reset()
        print("[TrackingController] 🔄 Reset PID tracker.")

    def update_pid_params(self, kp=None, ki=None, kd=None, forward_speed=None, max_turn_rate=None, **kwargs):
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
        print(f"[TrackingController] PID Updated -> Kp:{self.pid.Kp}, Ki:{self.pid.Ki}, Kd:{self.pid.Kd}, Speed:{self.forward_speed}m/s, MaxTurn:{self.max_turn_rate}deg/s")

    def compute_velocity(self, gate_center_x):
        """
        Hitung kecepatan & belokan langsung tanpa FSM state machine.
        - Objek terdeteksi -> Maju forward_speed, Belok PID(error_px).
        - Objek tidak ada -> Maju 0.0, Belok 0.0.
        """
        # Hitung error piksel dari tengah frame (range: -320 s/d +320)
        # error_px > 0: Objek di KANAN frame -> kapal harus Belok Kanan (+turn_rate)
        # error_px < 0: Objek di KIRI frame  -> kapal harus Belok Kiri (-turn_rate)
        error_px = float(gate_center_x - self.center_x)

        # simple_pid secara internal menghitung: (setpoint - input) = 0 - (-error_px) = +error_px
        # Ini memastikan error_px > 0 menghasilkan turn_rate POSITIF (+deg/s = Belok Kanan MAVLink)
        turn_rate = float(self.pid(-error_px))

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

        error_px = float(gate_center_x - self.center_x)
        raw_output = float(self.pid(-error_px))

        # Normalisasi output dari range [-max_turn_rate, +max_turn_rate] ke [-1.0, +1.0]
        steering_norm = raw_output / self.max_turn_rate if self.max_turn_rate > 0 else 0.0
        return max(-1.0, min(1.0, steering_norm))

