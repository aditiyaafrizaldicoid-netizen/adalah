import math
from pymavlink import mavutil
from sensors.state import ASVState

class MAVLinkParser:
    """
    Memparsing pesan MAVLink mentah yang masuk dari Pixhawk
    dan memperbarui objek ASVState.
    """
    def __init__(self, state: ASVState):
        self.state = state

    def parse_message(self, msg):
        if not msg:
            return

        msg_type = msg.get_type()

        if msg_type == "HEARTBEAT":
            self._parse_heartbeat(msg)
        elif msg_type == "GLOBAL_POSITION_INT":
            self._parse_global_position(msg)
        elif msg_type == "ATTITUDE":
            self._parse_attitude(msg)
        elif msg_type == "SYS_STATUS":
            self._parse_sys_status(msg)
        elif msg_type == "BATTERY_STATUS":
            self._parse_battery_status(msg)
        elif msg_type == "VFR_HUD":
            self._parse_vfr_hud(msg)
        elif msg_type == "STATUSTEXT":
            self._parse_status_text(msg)

    def _parse_heartbeat(self, msg):
        # Abaikan heartbeat yang berasal dari GCS/Base Station sendiri (system ID 255)
        if hasattr(msg, 'get_srcSystem') and msg.get_srcSystem() == 255:
            return

        is_armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
        
        # Mapping nama mode dari pymavlink atau fallback manual
        try:
            mode_mapping = mavutil.mode_mapping_bynumber(msg.type)
            mode_name = mode_mapping.get(msg.custom_mode, f"MODE_{msg.custom_mode}") if mode_mapping else f"MODE_{msg.custom_mode}"
        except Exception:
            # Fallback jika mode_mapping gagal
            mode_names = {
                0: "MANUAL/STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "STEERING/AUTO",
                4: "HOLD", 5: "LOITER", 10: "AUTO", 11: "RTL", 15: "GUIDED", 19: "MANUAL"
            }
            mode_name = mode_names.get(msg.custom_mode, f"MODE_{msg.custom_mode}")

        self.state.update_heartbeat(
            is_armed=is_armed,
            mode=mode_name,
            system_status=msg.system_status
        )

    def _parse_global_position(self, msg):
        # MAVLink mengirim koordinat dikali 1e7
        lat = msg.lat / 1e7
        lon = msg.lon / 1e7
        alt = msg.relative_alt / 1000.0  # mm ke meter
        
        # Heading kompas (msg.hdg dalam centidegrees, e.g. 36000 = 360 derajat)
        # Jika hdg = 65535 artinya tidak diketahui (maka fallback ke 0 atau nilai lama)
        heading = msg.hdg / 100.0 if msg.hdg != 65535 else -1.0
        
        # Kecepatan horizontal & vertikal (vx, vy, vz dalam cm/s diubah ke m/s)
        vx_m = msg.vx / 100.0
        vy_m = msg.vy / 100.0
        vz_m = msg.vz / 100.0
        ground_speed = math.sqrt(vx_m**2 + vy_m**2)

        self.state.update_gps(
            lat=lat, lon=lon, alt=alt, heading=heading, 
            ground_speed=ground_speed, vx=vx_m, vy=vy_m, vz=vz_m
        )

    def _parse_attitude(self, msg):
        # MAVLink ATTITUDE dalam radian (-pi hingga pi), kita ubah ke derajat
        roll_deg = math.degrees(msg.roll)
        pitch_deg = math.degrees(msg.pitch)
        yaw_deg = math.degrees(msg.yaw)
        if yaw_deg < 0:
            yaw_deg += 360.0

        self.state.update_attitude(roll=roll_deg, pitch=pitch_deg, yaw=yaw_deg)

    def _parse_sys_status(self, msg):
        # msg.voltage_battery adalah milivolt (mV)
        # msg.current_battery adalah miliampere (cA atau 10mA tergantung FC, umumnya 10 * mA)
        voltage = msg.voltage_battery / 1000.0 if msg.voltage_battery > 0 else 0.0
        current = msg.current_battery / 100.0 if msg.current_battery > 0 else 0.0
        remaining = msg.battery_remaining if msg.battery_remaining >= 0 else 0
        
        self.state.update_battery(voltage=voltage, current=current, remaining=remaining)

    def _parse_battery_status(self, msg):
        # Parsing alternatif jika FC menggunakan BATTERY_STATUS lengkap
        if hasattr(msg, 'voltages') and len(msg.voltages) > 0 and msg.voltages[0] != 65535:
            # Hitung total voltase cell
            total_mv = sum(v for v in msg.voltages if v != 65535)
            voltage = total_mv / 1000.0
            current = msg.current_battery / 100.0 if msg.current_battery != -1 else 0.0
            remaining = msg.battery_remaining if msg.battery_remaining != -1 else 0
            self.state.update_battery(voltage=voltage, current=current, remaining=remaining)

    def _parse_vfr_hud(self, msg):
        # Fallback jika GLOBAL_POSITION_INT hdg tidak tersedia
        # VFR_HUD memiliki heading langsung dalam derajat
        heading = float(msg.heading)
        ground_speed = float(msg.groundspeed)
        current_data = self.state.get_data()
        if current_data.heading == 0.0 or current_data.heading == -1.0:
            self.state.update_gps(
                lat=current_data.lat,
                lon=current_data.lon,
                alt=current_data.alt,
                heading=heading,
                ground_speed=ground_speed,
                vx=current_data.vx,
                vy=current_data.vy,
                vz=current_data.vz
            )

    def _parse_status_text(self, msg):
        try:
            text = msg.text.decode("utf-8", errors="ignore").rstrip("\x00")
            self.state.add_status_text(text)
        except Exception:
            pass
