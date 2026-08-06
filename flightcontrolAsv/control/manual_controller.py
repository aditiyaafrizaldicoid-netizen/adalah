"""
ManualRCController - Direct MAVLink MANUAL Mode RC Override Controller.

Channel Mapping Sesuai Spesifikasi User:
- Channel 1 (RCIN1 / Roll)    : Steering Kemudi Servo (1000 us = Kiri Penuh, 1500 us = Netral, 2000 us = Kanan Penuh)
- Channel 3 (RCIN3 / Throttle): ESC Motor Thruster (1000 us = Stop/0%, 2000 us = Full Forward/100%)
"""

import inspect
from connection.manager import ConnectionManager


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
        steer_norm = max(-1.0, min(1.0, float(steering_command)))
        pwm_steer = int(self.pwm_steer_center + (steer_norm * 500.0))
        pwm_steer = max(self.pwm_steer_min, min(self.pwm_steer_max, pwm_steer))

        # 2. Konversi Throttle (0.0 s/d 1.0) -> PWM Channel 3 (1000 s/d 2000 us, min 1000 us)
        thr_norm = max(0.0, min(1.0, float(throttle_command)))
        pwm_thr = int(self.pwm_thr_min + (thr_norm * 1000.0))
        pwm_thr = max(self.pwm_thr_min, min(self.pwm_thr_max, pwm_thr))

        # 3. Susun array 18 channel MAVLink (65535 = Abaikan / Lepaskan channel tersebut)
        sig = inspect.signature(self.connection.master.mav.rc_channels_override_send)
        max_channels = 18 if len(sig.parameters) >= 20 else 8

        rc_values = [65535] * max_channels
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

    def release_rc(self) -> bool:
        """Melepaskan seluruh override RC agar kendali kembali ke remote RC fisik."""
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            return False

        sig = inspect.signature(self.connection.master.mav.rc_channels_override_send)
        max_channels = 18 if len(sig.parameters) >= 20 else 8
        rc_values = [65535] * max_channels

        try:
            self.connection.master.mav.rc_channels_override_send(
                self.connection.config.TARGET_SYSTEM,
                self.connection.config.TARGET_COMPONENT,
                *rc_values
            )
            print("[ManualRCController] Override RC berhasil dilepaskan.")
            return True
        except Exception as e:
            print(f"[ManualRCController] Error release RC: {e}")
            return False
