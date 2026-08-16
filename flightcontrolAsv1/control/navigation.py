from pymavlink import mavutil
from connection.manager import ConnectionManager

class NavigationControl:
    """
    Mengendalikan pergerakan kapal saat berada dalam mode GUIDED.
    """
    def __init__(self, connection: ConnectionManager):
        self.connection = connection

    def send_velocity(self, forward_speed: float, turn_rate_deg: float = 0.0) -> bool:
        """
        Menggerakkan ArduRover / ArduBoat dengan kecepatan maju & belokan (Mode GUIDED).
        - forward_speed: Kecepatan maju dalam m/s (misal 0.5 m/s, negatif = mundur)
        - turn_rate_deg: Kecepatan belok dalam deg/s (positif = kanan, negatif = kiri)

        Spesifikasi MAVLink SET_POSITION_TARGET_LOCAL_NED untuk ArduRover Velocity + Yaw Rate:
        - Frame: MAV_FRAME_BODY_OFFSET_NED (relatif terhadap haluan kapal)
        - Bitmask (type_mask = 2023 / 0x07E7 / 0b0000_0111_1110_0111):
          * Bit 3 = 0  -> Gunakan Velocity X (forward_speed m/s)
          * Bit 4 = 0  -> Gunakan Velocity Y (0.0 m/s)
          * Bit 10 = 1 -> Abaikan Yaw Angle Target (bit 10 = 1024)
          * Bit 11 = 0 -> Gunakan Yaw Rate Target (yaw_rate_rad dalam rad/s)
        """
        if not self.connection.master:
            return False

        import math

        sys_id = getattr(self.connection.master, 'target_system', self.connection.config.TARGET_SYSTEM) or 1
        comp_id = getattr(self.connection.master, 'target_component', self.connection.config.TARGET_COMPONENT) or 1

        # Konversi kecepatan belok deg/s ke rad/s (+ = Kanan/CW, - = Kiri/CCW)
        yaw_rate_rad = math.radians(turn_rate_deg)

        # Bitmask 2023 (0x07E7): Aktifkan Vx (bit 3=0), Vy (bit 4=0), dan Yaw Rate (bit 11=0)
        # Abaikan: Pos X(1) + Pos Y(2) + Pos Z(4) + Vz(32) + Acc(64+128+256) + Force(512) + Yaw(1024) = 2023
        type_mask = 2023

        msg = self.connection.master.mav.set_position_target_local_ned_encode(
            0,                                           # time_boot_ms
            sys_id,
            comp_id,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED,   # Body offset frame (relatif haluan kapal)
            type_mask,
            0, 0, 0,                                    # Posisi X, Y, Z (diabaikan)
            forward_speed, 0.0, 0.0,                    # Vx (m/s), Vy (0.0), Vz (0.0)
            0, 0, 0,                                    # Akselerasi (diabaikan)
            0.0,                                        # Target Yaw Angle (diabaikan)
            yaw_rate_rad                                # Target Yaw Rate (rad/s)
        )
        return self.connection.send_message(msg)







    def goto_target(self, target_lat: float, target_lon: float) -> bool:
        """
        Memerintahkan kapal menuju ke koordinat GPS target (dalam mode GUIDED).
        """
        if not self.connection.master:
            return False

        # Bitmask: Aktifkan posisi lat/lon saja, abaikan alt, vel, acc, yaw
        # 0b0000_1111_1111_1000 = 0x0FF8
        type_mask = 0b0000_1111_1111_1000

        # MAVLink meminta koordinat dalam format integer (derajat * 1e7)
        lat_int = int(target_lat * 1e7)
        lon_int = int(target_lon * 1e7)

        msg = self.connection.master.mav.set_position_target_global_int_encode(
            0, # time_boot_ms
            self.connection.config.TARGET_SYSTEM,
            self.connection.config.TARGET_COMPONENT,
            mavutil.mavlink.MAV_FRAME_GLOBAL_INT,
            type_mask,
            lat_int, lon_int, 0,       # Target lat, lon, alt
            0, 0, 0,                   # Kecepatan (diabaikan)
            0, 0, 0,                   # Akselerasi (diabaikan)
            0, 0                       # Yaw & yaw rate (diabaikan)
        )
        print(f"[NavigationControl] Mengirim target menuju ({target_lat}, {target_lon})...")
        return self.connection.send_message(msg)

    def stop(self, silent: bool = False) -> bool:
        """
        Menghentikan pergerakan kapal secara langsung (kecepatan = 0).
        :param silent: Jika True, tidak print log (untuk keepalive berkala).
        """
        if not silent:
            print("[NavigationControl] Menghentikan kapal (Stop)...")
        return self.send_velocity(forward_speed=0.0, turn_rate_deg=0.0)

