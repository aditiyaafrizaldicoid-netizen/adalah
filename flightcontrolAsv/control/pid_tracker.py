from simple_pid import PID
import time


class TrackingController:
    """
    PID Tracking Controller untuk mode GUIDED ArduRover.

    Mengontrol ASV agar melewati gerbang (bola hijau + merah) tepat dari tengah,
    menggunakan MAVLink SET_POSITION_TARGET_LOCAL_NED via NavigationControl.send_velocity().

    State Machine:
    - SEARCHING  : Tidak ada gate terdeteksi, kapal berhenti.
    - ALIGNING   : Gate terdeteksi, kapal meluruskan diri ke tengah gate (gerak pelan + belok).
    - APPROACHING: Sudah cukup lurus, kapal maju penuh sambil koreksi kecil.
    - PASSING    : Kapal sedang melewati gate (maju lurus tanpa steering).
    - COOLDOWN   : Setelah berhasil lewat gate, jeda sebentar sebelum mencari gate berikutnya.
    """

    # State constants
    STATE_SEARCHING   = "SEARCHING"
    STATE_ALIGNING    = "ALIGNING"
    STATE_APPROACHING = "APPROACHING"
    STATE_PASSING     = "PASSING"
    STATE_COOLDOWN    = "COOLDOWN"

    def __init__(self, frame_width=640, kp=0.04, ki=0.001, kd=0.008,
                 forward_speed=1.0, align_threshold_px=40,
                 pass_duration=2.5, cooldown_duration=3.0):
        """
        :param frame_width:        Lebar frame kamera (pixel).
        :param kp:                 Proportional gain PID (output = turn rate deg/s).
        :param ki:                 Integral gain PID.
        :param kd:                 Derivative gain PID.
        :param forward_speed:      Kecepatan maju saat approaching / passing (m/s).
        :param align_threshold_px: Toleransi piksel dari tengah frame agar dianggap sudah lurus.
        :param pass_duration:      Durasi fase PASSING (detik) – kapal maju lurus melewati gate.
        :param cooldown_duration:  Durasi cooldown setelah melewati gate sebelum mencari lagi.
        """
        self.frame_width = frame_width
        self.center_x = frame_width // 2
        self.forward_speed = forward_speed
        self.align_threshold_px = align_threshold_px
        self.pass_duration = pass_duration
        self.cooldown_duration = cooldown_duration

        # PID: error = (gate_center_x - frame_center_x), output = turn_rate deg/s
        # Setpoint = 0 (error kita sudah dihitung sebelum di-feed ke PID)
        self.pid = PID(kp, ki, kd, setpoint=0.0)
        # Batasi turn rate: -30 hingga +30 deg/s``
        self.pid.output_limits = (-50.0, 50.0)

        # State machine
        self.state = self.STATE_SEARCHING
        self._state_start_time = time.time()
        self.last_seen_time = 0.0
        self._lost_timeout = 2.0  # detik sebelum kembali ke SEARCHING jika gate hilang

    def update_pid_params(self, kp=None, ki=None, kd=None, forward_speed=None, align_threshold_px=None):
        """Dynamic tuning PID & parameters dari Base Station secara live."""
        if kp is not None:
            self.pid.Kp = float(kp)
        if ki is not None:
            self.pid.Ki = float(ki)
        if kd is not None:
            self.pid.Kd = float(kd)
        if forward_speed is not None:
            self.forward_speed = float(forward_speed)
        if align_threshold_px is not None:
            self.align_threshold_px = float(align_threshold_px)
        print(f"[TrackingController] PID Parameters Updated -> Kp: {self.pid.Kp}, Ki: {self.pid.Ki}, Kd: {self.pid.Kd}, Speed: {self.forward_speed}m/s, AlignTol: {self.align_threshold_px}px")

    def _set_state(self, new_state: str):

        self.state = new_state
        self._state_start_time = time.time()
        print(f"[TrackingController] State -> {new_state}")

    def _state_elapsed(self) -> float:
        return time.time() - self._state_start_time

    def compute_velocity(self, gate_center_x):
        """
        Menghitung perintah kecepatan GUIDED-mode berdasarkan posisi tengah gate.

        :param gate_center_x: Koordinat X pixel midpoint gate (None jika tidak terdeteksi).
        :return: (forward_speed_ms, turn_rate_deg, state_label)
                 - forward_speed_ms : Kecepatan maju dalam m/s (kirim ke send_velocity).
                 - turn_rate_deg    : Kecepatan belok deg/s (positif=kanan, negatif=kiri).
                 - state_label      : String state saat ini (untuk debug / OSD).
        """
        now = time.time()

        # ---- COOLDOWN: Jeda setelah berhasil melewati gate ----
        if self.state == self.STATE_COOLDOWN:
            if self._state_elapsed() >= self.cooldown_duration:
                self._set_state(self.STATE_SEARCHING)
            return 0.0, 0.0, self.state

        # ---- PASSING: Maju lurus selama durasi tertentu ----
        if self.state == self.STATE_PASSING:
            if self._state_elapsed() >= self.pass_duration:
                print("[TrackingController] ✅ Gate berhasil dilewati! Masuk cooldown.")
                self._set_state(self.STATE_COOLDOWN)
                return 0.0, 0.0, self.state
            # Maju penuh, lurus (tidak ada steering)
            return self.forward_speed, 0.0, self.state

        # ---- Gate tidak terdeteksi ----
        if gate_center_x is None:
            if now - self.last_seen_time > self._lost_timeout:
                if self.state != self.STATE_SEARCHING:
                    self._set_state(self.STATE_SEARCHING)
            # Maju pelan (0.5 m/s) untuk mencari bola jika sedang SEARCHING
            search_speed = self.forward_speed * 0.5
            return search_speed, 0.0, self.state


        # ---- Gate terdeteksi ----
        self.last_seen_time = now

        # Hitung error: seberapa jauh midpoint gate dari tengah frame
        # error positif = gate ada di kanan -> perlu belok kanan
        # error negatif = gate ada di kiri  -> perlu belok kiri
        error = float(gate_center_x - self.center_x)
        abs_error = abs(error)

        # Feed error ke PID, output = turn_rate deg/s (positif = belok kanan, negatif = belok kiri)
        turn_rate = float(self.pid(error))


        # ---- SEARCHING -> ALIGNING ----
        if self.state == self.STATE_SEARCHING:
            self._set_state(self.STATE_ALIGNING)

        # ---- ALIGNING: Luruskan diri dulu, gerak pelan ----
        if self.state == self.STATE_ALIGNING:
            if abs_error <= self.align_threshold_px:
                # Sudah cukup lurus -> mulai approaching
                self._set_state(self.STATE_APPROACHING)
            slow_speed = self.forward_speed * 0.3
            return slow_speed, turn_rate, self.state

        # ---- APPROACHING: Maju penuh + koreksi kecil ----
        if self.state == self.STATE_APPROACHING:
            if abs_error > self.align_threshold_px * 2:
                # Gate bergeser terlalu jauh -> kembali aligning
                self._set_state(self.STATE_ALIGNING)
                return self.forward_speed * 0.3, turn_rate, self.state

            # Skala turn rate proporsional terhadap error (semakin lurus, semakin kecil koreksi)
            correction_scale = min(abs_error / (self.align_threshold_px * 2), 1.0)
            scaled_turn = turn_rate * correction_scale

            # Sudah sangat lurus -> masuk PASSING
            if abs_error <= self.align_threshold_px // 2:
                self._set_state(self.STATE_PASSING)
                return self.forward_speed, 0.0, self.state

            return self.forward_speed, scaled_turn, self.state

        # Fallback
        return 0.0, turn_rate, self.state


