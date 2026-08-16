import inspect
from pymavlink import mavutil
from connection.manager import ConnectionManager
from config import ChannelConfig


class MotionControl:
    """
    Mengelola kendali gerak manual ASV (Teleoperation / Joystick / RC Override).
    Berguna saat docking, manuver di perairan sempit, atau pengambilalihan manual oleh operator Base Station.
    """
    def __init__(self, connection: ConnectionManager, channel_config: ChannelConfig = None):
        self.connection = connection
        # channel_config dipakai oleh drive_dual_vectored; bisa diupdate runtime dari ws_client
        self.channel_config = channel_config or ChannelConfig()

    # ------------------------------------------------------------------ #
    #  RC OVERRIDE (Universal – Direkomendasikan)                          #
    # ------------------------------------------------------------------ #

    def send_rc_override(self, channels: list) -> bool:
        """
        Mengirim override sinyal PWM (1000 - 2000 µs) langsung ke channel servo/motor Pixhawk.

        Pada ArduRover / ArduBoat standar:
        - Channel 1: Steering (1000 = Kiri penuh, 1500 = Netral, 2000 = Kanan penuh)
        - Channel 3: Throttle (1000 = Mundur penuh / Stop, 1500 = Netral, 2000 = Maju penuh)
        * Untuk kapal Differential Skid Steer (2 motor kiri/kanan):
        - Channel 1: Motor Kiri, Channel 3: Motor Kanan (atau sebaliknya tergantung setup)

        :param channels: List berisi nilai PWM hingga 18 channel (65535 atau 0 = lepaskan override / pasrahkan ke FC)
        Contoh: send_rc_override([1500, 0, 1600, 0, 0, 0, 0, 0]) -> Steering netral (1500), Throttle maju (1600)
        """
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            return False

        # Cek versi pymavlink (MAVLink 1 = 8 channel, MAVLink 2 = 18 channel)
        sig = inspect.signature(self.connection.master.mav.rc_channels_override_send)
        max_channels = 18 if len(sig.parameters) >= 20 else 8

        rc_values = [65535] * max_channels
        for i, pwm in enumerate(channels[:max_channels]):
            if pwm is not None and pwm > 0:
                rc_values[i] = int(pwm)
            elif pwm == 0:
                rc_values[i] = 65535  # 0 atau 65535 pada MAVLink berarti release override channel tersebut

        try:
            self.connection.master.mav.rc_channels_override_send(
                self.connection.config.TARGET_SYSTEM,
                self.connection.config.TARGET_COMPONENT,
                *rc_values
            )
            return True
        except Exception as e:
            print(f"[MotionControl] Error mengirim RC Override: {e}")
            return False

    def send_manual_control(self, x: int = 0, y: int = 0, z: int = 500, r: int = 0, buttons: int = 0) -> bool:
        """
        Mengirim pesan MANUAL_CONTROL MAVLink (standar Gamepad / Joystick di QGC).

        :param x: Maju/Mundur (-1000 sampai 1000, 0 = netral) -> Throttle
        :param y: Kanan/Kiri (-1000 sampai 1000, 0 = netral)  -> Steering / Lateral
        :param z: Thrust / Kedalaman (0 sampai 1000, 500 = netral untuk kapal)
        :param r: Yaw / Rotasi (-1000 sampai 1000, 0 = netral) -> Belok kemudi
        :param buttons: Bitmask tombol gamepad (tombol 1 sampai 16)
        """
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            return False

        try:
            self.connection.master.mav.manual_control_send(
                self.connection.config.TARGET_SYSTEM,
                int(x), int(y), int(z), int(r), int(buttons)
            )
            return True
        except Exception as e:
            print(f"[MotionControl] Error mengirim MANUAL_CONTROL: {e}")
            return False

    def release_all_rc(self) -> bool:
        """Melepaskan semua override RC agar kontrol kembali sepenuhnya ke autopilot / remote fisik."""
        print("[MotionControl] Melepaskan semua override RC ke autopilot...")
        return self.send_rc_override([65535] * 18)


