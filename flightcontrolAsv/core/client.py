from typing import Dict, Any, Optional
from config import config, ASVConfig, ChannelConfig, channel_config
from core.state import ASVState, ASVStateData
from connection.manager import ConnectionManager
from control.arming import ArmingControl
from control.mode import ModeControl
from control.navigation import NavigationControl
from control.motion import MotionControl
from control.manual_controller import ManualRCController
from control.mission import MissionControl


class ASVController:
    """
    Class utama (Facade) untuk mengendalikan Autonomous Surface Vehicle (ASV) dari Mini PC.
    """
    def __init__(self, port: Optional[str] = None, baudrate: Optional[int] = None):
        # Gunakan custom config jika diberikan argumen
        self.config = ASVConfig()
        if port:
            self.config.CONNECTION_STRING = port
        if baudrate:
            self.config.BAUDRATE = baudrate

        # Shared channel config (singleton – bisa diupdate dari ws_client)
        self.channel_config = channel_config

        # Inisialisasi state & manager
        self.state = ASVState()
        self.connection = ConnectionManager(self.config, self.state)

        # Inisialisasi modul kontrol
        self._arming = ArmingControl(self.connection)
        self._mode = ModeControl(self.connection)
        self._navigation = NavigationControl(self.connection)
        self._motion = MotionControl(self.connection, self.channel_config)
        self._manual_rc = ManualRCController(self.connection, ch_steering=1, ch_throttle=3)
        self._mission = MissionControl(self.connection)

    # --- SIKLUS HIDUP KONEKSI ---
    def start(self):
        """Memulai background thread untuk koneksi MAVLink dan pembacaan telemetri."""
        print(f"[ASVController] Memulai sistem Flight Controller (Port: {self.config.CONNECTION_STRING})...")
        self.connection.start()

    def stop(self):
        """Menghentikan background thread dan menutup koneksi."""
        print("[ASVController] Menghentikan Flight Controller...")
        self.connection.stop()

    def is_connected(self) -> bool:
        """Mengecek apakah saat ini terhubung dan menerima heartbeat dari Pixhawk."""
        return self.state.get_data().is_connected

    # --- PEMBACAAN TELEMETRI & SENSOR ---
    def get_telemetry(self) -> ASVStateData:
        """Mengembalikan objek ASVStateData berisi seluruh telemetri kapal saat ini."""
        return self.state.get_data()

    def get_telemetry_dict(self) -> Dict[str, Any]:
        """Mengembalikan data telemetri dalam format dictionary (siap untuk dikirim via WebSocket/REST API)."""
        return self.state.to_dict()

    # --- CHANNEL CONFIGURATION (Runtime update dari Base Station) ---
    def update_channel_config(self, channel_map: dict) -> bool:
        """
        Memperbarui mapping channel aktuator (thruster/servo) secara runtime.
        Dipanggil dari ws_client saat menerima perintah 'set_channel_map' dari Base Station.

        :param channel_map: dict dengan key opsional:
            - thruster_left_ch  (int, 1-18)
            - thruster_right_ch (int, 1-18)
            - servo_left_ch     (int, 1-18)
            - servo_right_ch    (int, 1-18)
            - servo_method      (str, 'rc_override' | 'do_set_servo')
        """
        try:
            self.channel_config.update_from_dict(channel_map)
            return True
        except Exception as e:
            print(f"[ASVController] Gagal update channel config: {e}")
            return False

    def get_channel_config(self) -> dict:
        """Mengembalikan channel config saat ini dalam format dict (untuk dikirim ke base station)."""
        return self.channel_config.to_dict()

    # --- MANAJEMEN PARAMETER ARDUPILOT ---
    def set_param(self, param_name: str, value: float) -> bool:
        """
        Mengubah satu parameter ArduPilot via MAVLink PARAM_SET.
        Ekuivalen dengan mengedit parameter di Mission Planner.
        Perubahan TERSIMPAN di EEPROM Pixhawk (persisten setelah reboot).
        """
        return self.connection.send_param_set(param_name, value)

    def configure_guided_parameters(self, cruise_speed: float = 1.0, cruise_throttle: float = 50.0, atc_speed_p: float = 1.0) -> bool:
        """
        Mengonfigurasi parameter dasar Speed Controller ArduRover untuk Mode GUIDED.
        - CRUISE_SPEED: Kecepatan acuan m/s (default: 1.0 m/s)
        - CRUISE_THROTTLE: Persentase throttle dasar (%) untuk mencapai CRUISE_SPEED (default: 50.0%)
        - ATC_SPEED_P: Gain Proportional PID Kecepatan ArduRover (default: 1.0)
        """
        print(f"[ASVController] Menyetel parameter Mode GUIDED -> CRUISE_SPEED={cruise_speed}m/s, CRUISE_THROTTLE={cruise_throttle}%, ATC_SPEED_P={atc_speed_p}...")
        ok1 = self.set_param("CRUISE_SPEED", cruise_speed)
        ok2 = self.set_param("CRUISE_THROTTLE", cruise_throttle)
        ok3 = self.set_param("ATC_SPEED_P", atc_speed_p)
        return ok1 and ok2 and ok3



    # --- PERINTAH KONTROL (CONTROL COMMANDS) ---
    def arm(self, force: bool = False) -> bool:
        """Mengaktifkan (ARM) motor kapal."""
        return self._arming.arm(force=force)

    def disarm(self, force: bool = False) -> bool:
        """Mematikan (DISARM) motor kapal."""
        return self._arming.disarm(force=force)




    def set_mode(self, mode_name: str) -> bool:
        """
        Mengubah mode kapal. 
        Pilihan umum: 'MANUAL', 'HOLD', 'LOITER', 'GUIDED', 'AUTO', 'RTL'
        """
        return self._mode.set_mode(mode_name)

    # --- PERINTAH NAVIGASI (GUIDED MODE) ---
    def move_forward(self, speed: float) -> bool:
        """
        Bergerak maju dengan kecepatan tertentu (m/s).
        Wajib berada di mode GUIDED dan Armed.
        """
        return self._navigation.send_velocity(forward_speed=speed, turn_rate_deg=0.0)

    def turn(self, speed: float, turn_rate_deg: float) -> bool:
        """
        Bergerak maju sambil belok.
        turn_rate_deg positif = belok kanan, negatif = belok kiri.
        """
        return self._navigation.send_velocity(forward_speed=speed, turn_rate_deg=turn_rate_deg)

    def goto(self, lat: float, lon: float) -> bool:
        """
        Memerintahkan kapal berlayar menuju koordinat GPS target.
        Wajib berada di mode GUIDED dan Armed.
        """
        return self._navigation.goto_target(target_lat=lat, target_lon=lon)

    def stop_movement(self, silent: bool = False) -> bool:
        """Menghentikan pergerakan kapal segera (Set kecepatan ke 0)."""
        return self._navigation.stop(silent=silent)


    # --- KENDALI MANUAL / JOYSTICK (TELEOPERATION) ---
    def send_rc_override(self, channels: list) -> bool:
        """
        Mengirim override PWM langsung ke motor/servo kapal (1000 - 2000 µs, 0/65535 = lepaskan).
        Contoh: send_rc_override([1500, 0, 1600]) -> Steering netral (1500), Throttle maju (1600)
        """
        return self._motion.send_rc_override(channels)

    def send_manual_control(self, x: int = 0, y: int = 0, z: int = 500, r: int = 0, buttons: int = 0) -> bool:
        """
        Mengirim pesan MANUAL_CONTROL MAVLink dari Joystick/Gamepad.
        x: Throttle (-1000..1000), y: Steering (-1000..1000), z: Thrust (0..1000), r: Yaw (-1000..1000)
        """
        return self._motion.send_manual_control(x, y, z, r, buttons)

    def release_rc(self) -> bool:
        """Melepaskan semua override RC agar kontrol kembali ke remote atau mode otomatis autopilot."""
        return self._motion.release_all_rc()

    def send_manual_rc_drive(self, steering_norm: float, throttle_norm: float) -> bool:
        """
        Mengirim sinyal kemudi (Ch 1) & throttle (Ch 3) langsung ke Pixhawk via MAVLink RC Override (MANUAL Mode).
        - steering_norm: -1.0 (Belok Kiri 1000us) s/d +1.0 (Belok Kanan 2000us), 0.0 = Netral (1500us)
        - throttle_norm: 0.0 (Stop 1000us) s/d 1.0 (Full Forward 2000us)
        """
        return self._manual_rc.send_drive_command(steering_norm, throttle_norm)



    # --- MANAJEMEN MISI WAYPOINT (AUTONOMOUS SURVEY) ---
    def upload_mission(self, waypoints: list) -> bool:
        """
        Mengunggah rute titik survei / waypoint ke dalam Pixhawk.
        Format waypoints: [{"lat": -6.123, "lon": 106.123, "speed_ms": 1.5, "hold_sec": 0}, ...]
        """
        return self._mission.upload_waypoints(waypoints)

    def clear_mission(self) -> bool:
        """Menghapus seluruh waypoint dari memori Pixhawk."""
        return self._mission.clear_all()

    def set_current_waypoint(self, seq: int) -> bool:
        """Mengubah target titik rute aktif saat dalam mode AUTO ke nomor urut tertentu."""
        return self._mission.set_current_waypoint(seq)
