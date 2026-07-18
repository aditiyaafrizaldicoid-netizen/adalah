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
        Menggerakkan kapal dengan kecepatan tertentu (dalam mode GUIDED).
        - forward_speed: Kecepatan maju dalam m/s (negatif untuk mundur)
        - turn_rate_deg: Kecepatan belok/rotation dalam derajat/detik (positif kanan, negatif kiri)
        """
        if not self.connection.master:
            return False

        # Bitmask: Kita abaikan posisi & akselerasi, kita HANYA gunakan kecepatan (vx) dan yaw rate
        # 0b0000_0111_1101_1111 = 0x07DF (Abaikan pos x/y/z, abaikan vy/vz, abaikan afx/afy/afz, abaikan yaw)
        # Aktifkan vx (maju) dan yaw_rate (belok)
        type_mask = 0b0000_0111_1101_1111

        import math
        yaw_rate_rad = math.radians(turn_rate_deg)

        # Pesan SET_POSITION_TARGET_LOCAL_NED dengan coordinate frame BODY_NED (relatif terhadap kepala kapal)
        msg = self.connection.master.mav.set_position_target_local_ned_encode(
            0, # time_boot_ms
            self.connection.config.TARGET_SYSTEM,
            self.connection.config.TARGET_COMPONENT,
            mavutil.mavlink.MAV_FRAME_BODY_NED,
            type_mask,
            0, 0, 0,                   # Posisi x, y, z (diabaikan)
            forward_speed, 0, 0,       # Kecepatan vx (maju), vy, vz
            0, 0, 0,                   # Akselerasi (diabaikan)
            0,                         # Target yaw angle (diabaikan)
            yaw_rate_rad               # Target yaw rate (belok rad/s)
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

    def stop(self) -> bool:
        """
        Menghentikan pergerakan kapal secara langsung (kecepatan = 0).
        """
        print("[NavigationControl] Menghentikan kapal (Stop)...")
        return self.send_velocity(forward_speed=0.0, turn_rate_deg=0.0)
