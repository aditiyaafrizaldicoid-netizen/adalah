import inspect
from pymavlink import mavutil
from connection.manager import ConnectionManager
from config import ChannelConfig
from control.manual_source import RC_IGNORE, RC_RELEASE


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

        :param channels: List nilai PWM hingga 18 channel. Arti nilai khusus (sesuai
            spesifikasi MAVLink RC_CHANNELS_OVERRIDE — JANGAN disamakan):
              0     = LEPASKAN channel ini, kembalikan ke receiver RC / remote fisik
              65535 = ABAIKAN field ini, override channel ini tetap seperti sebelumnya
              None  = sama dengan 65535 (channel tidak disebut dalam perintah ini)
        Contoh: send_rc_override([1500, None, 1600]) -> Steering netral (1500), Throttle maju (1600)

        CATATAN: versi lama menerjemahkan 0 menjadi 65535 karena mengira keduanya sama-sama
        berarti "lepas". Akibatnya release_all_rc() tidak pernah benar-benar melepaskan
        apa pun dan remote RC fisik tidak bisa mengambil alih — lihat control/manual_source.py.
        """
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            return False

        # Cek versi pymavlink (MAVLink 1 = 8 channel, MAVLink 2 = 18 channel)
        sig = inspect.signature(self.connection.master.mav.rc_channels_override_send)
        max_channels = 18 if len(sig.parameters) >= 20 else 8

        rc_values = [RC_IGNORE] * max_channels
        for i, pwm in enumerate(channels[:max_channels]):
            if pwm is None:
                continue                 # tidak disebut → biarkan channel apa adanya
            rc_values[i] = int(pwm)      # termasuk 0, yang berarti LEPASKAN channel ini

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

    def release_all_rc(self, verbose: bool = True) -> bool:
        """
        Melepaskan semua override RC agar kontrol kembali sepenuhnya ke autopilot /
        remote RC fisik. Mengirim RC_RELEASE (0) ke seluruh channel.
        """
        if verbose:
            print("[MotionControl] Melepaskan semua override RC (semua channel = 0)...")
        return self.send_rc_override([RC_RELEASE] * 18)


