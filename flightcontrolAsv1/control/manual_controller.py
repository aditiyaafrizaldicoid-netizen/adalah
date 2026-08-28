"""
ManualRCController - Direct MAVLink MANUAL Mode RC Override Controller.

Channel Mapping Sesuai Spesifikasi User:
- Channel 1 (RCIN1 / Roll)    : Steering Kemudi Servo (1000 us = Kiri Penuh, 1500 us = Netral, 2000 us = Kanan Penuh)
- Channel 3 (RCIN3 / Throttle): ESC Motor Thruster (1000 us = Stop/0%, 2000 us = Full Forward/100%)
"""

import inspect
from connection.manager import ConnectionManager
from control.manual_source import RC_IGNORE, RC_RELEASE


class ManualRCController:
    """
    Mengontrol pergerakan kapal dalam MANUAL Mode dengan mengirim MAVLink RC_CHANNELS_OVERRIDE.
    Jetson bertindak sebagai pengambil keputusan penuh tanpa interference Heading Controller ArduPilot.
    """

    def __init__(self, connection: ConnectionManager, ch_steering: int = 1, ch_throttle: int = 3):
        """
        :param connection: Modul ConnectionManager MAVLink.
        :param ch_steering: Nomor Channel MAVLink untuk Steering Roll (default: Channel 1 / RCIN1).
        :param ch_throttle: Nomor Channel MAVLink untuk Throttle (default: Channel 3 / RCIN3).
        """
        self.connection = connection
        self.ch_steering = ch_steering
        self.ch_throttle = ch_throttle

        # Batas PWM
        self.pwm_steer_min = 1000
        self.pwm_steer_center = 1500
        self.pwm_steer_max = 2000

        self.pwm_thr_min = 1000   # 0% Throttle / Stop
        self.pwm_thr_max = 2000   # 100% Throttle / Full Speed

        # Thruster trim: kompensasi ketidakseimbangan motor port vs starboard
        # Range: -1.0 to +1.0, diterjemahkan ke offset PWM steering (±250us)
        self.port_trim = 0.0
        self.starboard_trim = 0.0

    def set_trim(self, port: float, starboard: float):
        """Set thruster trim offset untuk kompensasi motor imbalance."""
        self.port_trim = max(-1.0, min(1.0, float(port)))
        self.starboard_trim = max(-1.0, min(1.0, float(starboard)))
        print(f"[ManualRCController] Trim set: port={self.port_trim:+.3f}, starboard={self.starboard_trim:+.3f}")

    def send_drive_command(self, steering_command: float, throttle_command: float) -> bool:
        """
        Konversi sinyal norma steering & throttle menjadi sinyal PWM RC Override.

        :param steering_command: Sinyal kemudi ter-normalisasi (-1.0 = Kiri, 0.0 = Netral, +1.0 = Kanan).
        :param throttle_command: Sinyal throttle ter-normalisasi (0.0 = Stop 1000us, 1.0 = Max 2000us).
        :return: True jika perintah MAVLink berhasil terkirim.
        """
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            return False

        # 1. Konversi Steering (-1.0 s/d +1.0) -> PWM Channel 1 (1000 s/d 2000 us, center 1500 us)
        # CATATAN: Di ArduRover MANUAL skid-steer, PWM > 1500 pada Ch1 mengaktifkan motor kanan
        # lebih kencang dari kiri → kapal belok KIRI. Ini kebalikan dari konvensi kita
        # (steer_norm > 0 = kanan). Maka kita negasi sebelum konversi ke PWM.
        steer_norm = max(-1.0, min(1.0, float(-steering_command)))  # negasi untuk kompensasi ArduRover
        # Trim: selisih port-starboard diterjemahkan ke offset PWM steering
        # port_trim > starboard_trim → motor port lebih kuat → perlu kompensasi ke kanan (PWM steering turun)
        trim_pwm = int((self.port_trim - self.starboard_trim) * 250.0)
        pwm_steer = int(self.pwm_steer_center + (steer_norm * 500.0)) + trim_pwm
        pwm_steer = max(self.pwm_steer_min, min(self.pwm_steer_max, pwm_steer))

        # 2. Konversi Throttle (0.0 s/d 1.0) -> PWM Channel 3 (1000 s/d 2000 us, min 1000 us)
        thr_norm = max(0.0, min(1.0, float(throttle_command)))
        pwm_thr = int(self.pwm_thr_min + (thr_norm * 1000.0))
        pwm_thr = max(self.pwm_thr_min, min(self.pwm_thr_max, pwm_thr))

        # 3. Susun array 18 channel MAVLink. RC_IGNORE (65535) = jangan sentuh channel
        #    itu — BUKAN "lepaskan". Yang melepaskan ke remote fisik adalah RC_RELEASE (0),
        #    lihat release_rc() & control/manual_source.py.
        sig = inspect.signature(self.connection.master.mav.rc_channels_override_send)
        max_channels = 18 if len(sig.parameters) >= 20 else 8

        rc_values = [RC_IGNORE] * max_channels
        rc_values[self.ch_steering - 1] = int(pwm_steer)
        rc_values[self.ch_throttle - 1] = int(pwm_thr)

        try:
            self.connection.master.mav.rc_channels_override_send(
                self.connection.config.TARGET_SYSTEM,
                self.connection.config.TARGET_COMPONENT,
                *rc_values
            )
            return True
        except Exception as e:
            print(f"[ManualRCController] Error mengirim RC Override: {e}")
            return False

    def stop(self) -> bool:
        """Failsafe / Emergency Stop: Set Throttle ke 0% (1000us) dan Steering ke Netral (1500us)."""
        return self.send_drive_command(steering_command=0.0, throttle_command=0.0)

    def release_rc(self, verbose: bool = True) -> bool:
        """
        Melepaskan seluruh override RC agar kendali kembali ke remote RC fisik.

        Mengirim RC_RELEASE (0) ke semua channel — BUKAN 65535. Versi lama file ini
        mengirim 65535, yang di MAVLink berarti "abaikan field ini" sehingga override
        yang sedang berjalan tetap dipertahankan dan remote tidak pernah dapat kendali.
        Lihat control/manual_source.py untuk penjelasan lengkapnya.

        Melepaskan override saja TIDAK cukup kalau mini PC masih mengirim override tiap
        frame — pemanggil wajib menghentikan pengiriman itu lebih dulu (lihat
        ASVController.set_manual_source()).
        """
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            return False

        sig = inspect.signature(self.connection.master.mav.rc_channels_override_send)
        max_channels = 18 if len(sig.parameters) >= 20 else 8
        rc_values = [RC_RELEASE] * max_channels

        try:
            self.connection.master.mav.rc_channels_override_send(
                self.connection.config.TARGET_SYSTEM,
                self.connection.config.TARGET_COMPONENT,
                *rc_values
            )
            if verbose:
                print("[ManualRCController] Override RC dilepaskan (semua channel = 0).")
            return True
        except Exception as e:
            print(f"[ManualRCController] Error release RC: {e}")
            return False
