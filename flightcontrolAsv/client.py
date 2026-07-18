from typing import Dict, Any, Optional
from config import config, ASVConfig, ChannelConfig, channel_config
from sensors.state import ASVState, ASVStateData
from connection.manager import ConnectionManager
from control.arming import ArmingControl
from control.mode import ModeControl
from control.navigation import NavigationControl
from control.motion import MotionControl
from control.mission import MissionControl

class ASVController:
    """
    Class utama (Facade) untuk mengendalikan Autonomous Surface Vehicle (ASV) dari Mini PC.
    
    Contoh Penggunaan di Backend Mini PC:
        from flight_controller.client import ASVController
        
        asv = ASVController(port="/dev/ttyACM0", baudrate=115200)
        asv.start()
        
        # Baca telemetri
        data = asv.get_telemetry()
        print(f"Baterai: {data.battery_voltage} V, GPS: {data.lat}, {data.lon}")
        
        # Kontrol kapal
        asv.arm()
        asv.set_mode("GUIDED")
        asv.move_forward(speed=1.5) # m/s
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

    def apply_no_rc_mode(self) -> dict:
        """
        Menerapkan konfigurasi parameter ArduRover untuk operasi TANPA RC receiver.
        Menonaktifkan semua failsafe yang berkaitan dengan sinyal RC, dan 
        mengeset fungsi Servo ke RCPassThru agar RC Override bekerja.
        """
        params_to_set = {
            "FS_THR_ENABLE":    0,   # Disable RC throttle failsafe
            "ARMING_CHECK":     0,   # Disable pre-arm checks (GPS, RC, compass, dll)
            "BRD_SAFETY_DEFLT": 0,   # Disable safety switch / press-to-arm
            "FS_GCS_ENABLE":    0,   # Disable GCS heartbeat failsafe
        }
        
        # Tambahkan SERVOx_FUNCTION = 1 (RCPassThru) untuk channel aktif
        active_channels = [
            self.channel_config.thruster_left_ch,
            self.channel_config.thruster_right_ch,
            self.channel_config.servo_left_ch,
            self.channel_config.servo_right_ch
        ]
        
        for ch in active_channels:
            if 1 <= ch <= 18:
                params_to_set[f"SERVO{ch}_FUNCTION"] = 1

        results = {}
        for name, value in params_to_set.items():
            ok = self.set_param(name, value)
            results[name] = "OK" if ok else "FAILED"
            import time; time.sleep(0.05)  # Jeda kecil antar parameter
        
        print(f"[ASVController] apply_no_rc_mode results: {results}")
        return results

    def restore_default_failsafe(self) -> dict:
        """
        Memulihkan failsafe ke nilai default ArduRover setelah selesai testing.
        Penting untuk keamanan di lapangan!
        """
        params_default = {
            "FS_THR_ENABLE":    1,   # Enable: HOLD saat RC hilang
            "ARMING_CHECK":     1,   # Enable semua pre-arm checks
            "BRD_SAFETY_DEFLT": 1,   # Enable safety switch
            "FS_GCS_ENABLE":    1,   # Enable GCS failsafe
        }
        results = {}
        for name, value in params_default.items():
            ok = self.set_param(name, value)
            results[name] = "OK" if ok else "FAILED"
            import time; time.sleep(0.1)
        print(f"[ASVController] restore_default_failsafe results: {results}")
        return results

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

    def stop_movement(self) -> bool:
        """Menghentikan pergerakan kapal segera (Set kecepatan ke 0)."""
        return self._navigation.stop()

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

    def set_servo(self, channel: int, pwm: int) -> bool:
        """
        Mengontrol posisi satu output servo secara langsung (misal untuk 2 Servo Belokan Thruster).
        :param channel: Nomor channel di Pixhawk (1 - 16)
        :param pwm: Nilai PWM (1000 = minimum/kiri, 1500 = tengah, 2000 = maksimum/kanan)
        """
        return self._motion.set_servo(channel, pwm)

    def drive_dual_vectored(self, throttle_left: int = 1500, throttle_right: int = 1500,
                            servo_left: int = 1500, servo_right: int = 1500, channels_map: dict = None) -> bool:
        """
        Kendali serentak khusus kapal 2 Thruster + 2 Servo Steering (Vectored Thrust).
        :param throttle_left: PWM Thruster Kiri (1000 mundur, 1500 stop, 2000 maju)
        :param throttle_right: PWM Thruster Kanan (1000 mundur, 1500 stop, 2000 maju)
        :param servo_left: PWM Servo Kiri (1000 kiri, 1500 lurus, 2000 kanan)
        :param servo_right: PWM Servo Kanan (1000 kiri, 1500 lurus, 2000 kanan)
        """
        return self._motion.drive_dual_vectored(throttle_left, throttle_right, servo_left, servo_right, channels_map)

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
