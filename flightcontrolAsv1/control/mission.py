import time
from pymavlink import mavutil
from connection.manager import ConnectionManager

class MissionControl:
    """
    Mengelola misi perjalanan otomatis (Waypoints / Rute Survei) pada ASV.
    """
    def __init__(self, connection: ConnectionManager):
        self.connection = connection

    def clear_all(self) -> bool:
        """Menghapus semua titik rute / waypoint yang ada di memori Pixhawk."""
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            return False

        print("[MissionControl] Menghapus semua waypoint di Pixhawk...")
        try:
            self.connection.master.mav.mission_clear_all_send(
                self.connection.config.TARGET_SYSTEM,
                self.connection.config.TARGET_COMPONENT
            )
            return True
        except Exception as e:
            print(f"[MissionControl] Error clear mission: {e}")
            return False

    def upload_waypoints(self, waypoints: list) -> bool:
        """
        Mengunggah daftar titik koordinat (Waypoints) ke Pixhawk.
        :param waypoints: List of dict dengan format:
            [
                {"lat": -6.12345, "lon": 106.12345, "speed_ms": 1.5, "hold_sec": 0},
                {"lat": -6.12500, "lon": 106.12500, "speed_ms": 1.5, "hold_sec": 5}
            ]
        Return True jika semua waypoint berhasil diakui oleh Pixhawk (MISSION_ACK).
        """
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            print("[MissionControl] Tidak bisa upload misi: ROV/ASV tidak terhubung.")
            return False

        if not waypoints:
            return self.clear_all()

        print(f"[MissionControl] Memulai upload {len(waypoints)} waypoint...")
        
        # 1. Clear misi sebelumnya
        self.clear_all()
        time.sleep(0.5)

        # Di ArduPilot / ArduRover, seq 0 adalah Home/Dummy waypoint, seq 1 s/d N adalah target kita
        total_items = len(waypoints) + 1

        try:
            with self.connection._write_lock:
                self.connection.master.mav.mission_count_send(
                    self.connection.config.TARGET_SYSTEM,
                    self.connection.config.TARGET_COMPONENT,
                    total_items,
                    mavutil.mavlink.MAV_MISSION_TYPE_MISSION
                )

            # 2. Menunggu permintaan MISSION_REQUEST_INT dari Pixhawk
            for seq in range(total_items):
                req = self.connection.master.recv_match(type=['MISSION_REQUEST_INT', 'MISSION_REQUEST'], blocking=True, timeout=5.0)
                if not req:
                    print(f"[MissionControl] Timeout menunggu MISSION_REQUEST untuk seq {seq}")
                    return False
                
                req_seq = getattr(req, 'seq', seq)
                print(f"[MissionControl] Mengirim waypoint seq {req_seq}/{total_items-1}...")

                if req_seq == 0:
                    # Seq 0: Home Position / Current Location
                    current = self.connection.state.get_data()
                    lat_int = int(current.lat * 1e7) if current.lat != 0 else int(waypoints[0]["lat"] * 1e7)
                    lon_int = int(current.lon * 1e7) if current.lon != 0 else int(waypoints[0]["lon"] * 1e7)
                    command = mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
                    param1, param2, param3, param4 = 0, 0, 0, 0
                else:
                    wp = waypoints[req_seq - 1]
                    lat_int = int(wp["lat"] * 1e7)
                    lon_int = int(wp["lon"] * 1e7)
                    command = mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
                    # Param1: Hold time (detik), Param2: Accept radius (meter), Param3: Pass radius, Param4: Yaw
                    param1 = float(wp.get("hold_sec", 0))
                    param2 = 2.0  # Accept radius 2 meter
                    param3 = 0.0
                    param4 = 0.0

                with self.connection._write_lock:
                    self.connection.master.mav.mission_item_int_send(
                        self.connection.config.TARGET_SYSTEM,
                        self.connection.config.TARGET_COMPONENT,
                        req_seq,
                        mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                        command,
                        req_seq == 0, # current (true untuk seq 0)
                        1,            # autocontinue
                        param1, param2, param3, param4,
                        lat_int, lon_int, 0,
                        mavutil.mavlink.MAV_MISSION_TYPE_MISSION
                    )

            # 3. Tunggu MISSION_ACK (Misi diterima)
            ack = self.connection.master.recv_match(type='MISSION_ACK', blocking=True, timeout=5.0)
            if ack and ack.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
                print("[MissionControl] Berhasil! Semua waypoint telah diunggah dan diverifikasi Pixhawk.")
                return True
            else:
                print(f"[MissionControl] Gagal verifikasi misi. Respon ACK: {ack.type if ack else 'No ACK'}")
                return False

        except Exception as e:
            print(f"[MissionControl] Error selama upload misi: {e}")
            return False

    def set_current_waypoint(self, seq: int) -> bool:
        """Mengubah target waypoint aktif ke nomor urutan tertentu (seq)."""
        if not self.connection.master or not self.connection.state.get_data().is_connected:
            return False
        try:
            with self.connection._write_lock:
                self.connection.master.mav.mission_set_current_send(
                    self.connection.config.TARGET_SYSTEM,
                    self.connection.config.TARGET_COMPONENT,
                    int(seq)
                )
            return True
        except Exception as e:
            print(f"[MissionControl] Error set current waypoint: {e}")
            return False
