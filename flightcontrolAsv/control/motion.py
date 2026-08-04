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

    # ------------------------------------------------------------------ #
    #  SET SERVO (DO_SET_SERVO – Hanya untuk AUX yang belum di-assign)    #
    # ------------------------------------------------------------------ #

    def set_servo(self, channel: int, pwm: int) -> bool:
        """
        Mengontrol posisi atau kecepatan satu output servo/motor PWM tertentu secara langsung di Pixhawk.

        ⚠️  PERHATIAN: ArduPilot akan MEMBLOKIR MAV_CMD_DO_SET_SERVO jika channel sudah di-assign ke fungsi
            (seperti Throttle / Steering). Gunakan hanya untuk channel AUX yang FUNCTION = Disabled (0).
            Untuk channel MAIN/AUX yang sudah di-assign fungsi, gunakan send_rc_override() sebagai gantinya.

        :param channel: Nomor channel output servo di Pixhawk (1 sampai 16)
        :param pwm: Nilai PWM (biasanya 1000 = kiri/minimum, 1500 = tengah, 2000 = kanan/maksimum)
        """
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            return False

        # Jika method yang dikonfigurasi adalah rc_override, gunakan itu sebagai pengganti
        if self.channel_config.servo_method == "rc_override":
            print(f"[MotionControl] set_servo: Fallback ke RC Override untuk ch {channel} = {pwm} µs")
            return self._set_single_channel_via_rc_override(channel, pwm)

        print(f"[MotionControl] Setting servo ch {channel} to {pwm} µs via DO_SET_SERVO")
        try:
            return self.connection.send_command_long(
                mavutil.mavlink.MAV_CMD_DO_SET_SERVO,
                int(channel),
                int(pwm)
            )
        except Exception as e:
            print(f"[MotionControl] Error set_servo (Ch {channel}): {e}")
            return False

    def _set_single_channel_via_rc_override(self, channel: int, pwm: int) -> bool:
        """
        Helper internal: Set satu channel tertentu via RC Override tanpa mengubah channel lain.
        """
        if channel < 1 or channel > 18:
            print(f"[MotionControl] Channel {channel} di luar range (1-18)")
            return False
        rc_channels = [65535] * 18
        rc_channels[channel - 1] = int(pwm)
        return self.send_rc_override(rc_channels)

    # ------------------------------------------------------------------ #
    #  DUAL VECTORED THRUST (Thruster L/R + Servo L/R)                   #
    # ------------------------------------------------------------------ #

    def drive_dual_vectored(self, throttle_left: int, throttle_right: int,
                            servo_left: int, servo_right: int,
                            channels_map: dict = None) -> bool:
        """
        Helper khusus untuk kapal ASV berkonsep 2 Thruster + 2 Servo Steering (Vectored Thrust).
        Mengirimkan perintah PWM secara serentak via RC Override.

        Channel mapping diambil dari ChannelConfig yang bisa diubah runtime dari Base Station.
        Jika channels_map diberikan, nilai itu akan di-override untuk pemanggilan ini.

        :param throttle_left: Nilai PWM untuk Thruster Kiri (1000 = mundur penuh, 1500 = stop, 2000 = maju penuh)
        :param throttle_right: Nilai PWM untuk Thruster Kanan (1000 = mundur penuh, 1500 = stop, 2000 = maju penuh)
        :param servo_left: Nilai PWM sudut Servo Belokan Kiri (1000 = kiri penuh, 1500 = lurus, 2000 = kanan penuh)
        :param servo_right: Nilai PWM sudut Servo Belokan Kanan (1000 = kiri penuh, 1500 = lurus, 2000 = kanan penuh)
        :param channels_map: Opsional override dict: {"thruster_left_ch": 1, "thruster_right_ch": 3, ...}
        """
        # Ambil channel dari config (bisa diupdate runtime) atau override dari argumen
        cfg = self.channel_config
        tl_ch = channels_map.get("thruster_left_ch", cfg.thruster_left_ch) if channels_map else cfg.thruster_left_ch
        tr_ch = channels_map.get("thruster_right_ch", cfg.thruster_right_ch) if channels_map else cfg.thruster_right_ch
        sl_ch = channels_map.get("servo_left_ch", cfg.servo_left_ch) if channels_map else cfg.servo_left_ch
        sr_ch = channels_map.get("servo_right_ch", cfg.servo_right_ch) if channels_map else cfg.servo_right_ch

        print(f"[MotionControl] drive_dual_vectored | TL:ch{tl_ch}={throttle_left} TR:ch{tr_ch}={throttle_right} "
              f"SL:ch{sl_ch}={servo_left} SR:ch{sr_ch}={servo_right}")

        # Mendukung hingga 18 channel (MAIN 1-8, AUX 1-10 → ch 9-18)
        rc_channels = [65535] * 18

        def set_ch(ch_num: int, val: int):
            if 1 <= ch_num <= 18:
                rc_channels[ch_num - 1] = int(val)
            else:
                print(f"[MotionControl] Peringatan: channel {ch_num} di luar range (1-18), diabaikan.")

        set_ch(tl_ch, throttle_left)
        set_ch(tr_ch, throttle_right)
        set_ch(sl_ch, servo_left)
        set_ch(sr_ch, servo_right)

        return self.send_rc_override(rc_channels)
