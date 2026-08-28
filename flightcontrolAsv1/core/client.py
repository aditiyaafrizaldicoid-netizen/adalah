import threading
import time
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
from control import manual_source


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

        # GPS offset: diterapkan saat mengirim telemetri ke base station
        self._gps_lat_offset = 0.0
        self._gps_lon_offset = 0.0

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

        # Sumber kendali manual aktif: mini PC (default) atau remote RC fisik.
        # Saat REMOTE, SELURUH perintah gerak dari mini PC diblokir di facade ini —
        # lihat set_manual_source() dan _blocked_by_remote().
        self._manual_source = manual_source.MINIPC
        self._manual_source_lock = threading.RLock()
        self._remote_block_last_log = 0.0

    @property
    def nav(self) -> 'NavigationControl':
        """Alias publik ke NavigationControl — dipakai oleh MissionEngine untuk send_velocity."""
        return self._navigation

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

    def get_telemetry_dict_with_offset(self) -> Dict[str, Any]:
        """Sama seperti get_telemetry_dict() tapi menerapkan GPS offset jika ada."""
        t = self.state.to_dict()
        if self._gps_lat_offset != 0.0:
            t['lat'] = (t.get('lat') or 0.0) + self._gps_lat_offset
        if self._gps_lon_offset != 0.0:
            t['lon'] = (t.get('lon') or 0.0) + self._gps_lon_offset
        return t

    def set_gps_offset(self, lat_offset: float, lng_offset: float) -> bool:
        """Set offset koreksi GPS. Diterapkan ke telemetri yang dikirim ke base station."""
        self._gps_lat_offset = float(lat_offset)
        self._gps_lon_offset = float(lng_offset)
        print(f"[ASVController] GPS offset: lat={lat_offset:+.7f}, lng={lng_offset:+.7f}")
        return True

    def set_thruster_trim(self, port_offset: float, starboard_offset: float) -> bool:
        """Set trim offset thruster untuk kompensasi ketidakseimbangan motor."""
        self._manual_rc.set_trim(
            max(-1.0, min(1.0, float(port_offset))),
            max(-1.0, min(1.0, float(starboard_offset)))
        )
        return True

    def start_imu_calibration(self, cal_type: str = 'gyro') -> bool:
        """
        Mulai kalibrasi IMU via MAVLink MAV_CMD_PREFLIGHT_CALIBRATION.
        cal_type: 'gyro' | 'accel_level' | 'compass'
        """
        MAV_CMD_PREFLIGHT_CALIBRATION = 241
        p1 = p2 = p3 = p4 = p5 = p6 = p7 = 0

        if cal_type == 'gyro':
            p1 = 1          # Gyroscope calibration
        elif cal_type == 'accel_level':
            p5 = 2          # Simple accelerometer level calibration
        elif cal_type == 'compass':
            p2 = 1          # Magnetometer (compass) calibration
        else:
            p1 = 1          # Default: gyro

        print(f"[ASVController] Starting IMU calibration: {cal_type} (p1={p1} p2={p2} p5={p5})")
        return self.connection.send_command_long(
            MAV_CMD_PREFLIGHT_CALIBRATION, p1, p2, p3, p4, p5, p6, p7
        )

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
        if self._blocked_by_remote("move_forward"):
            return False
        return self._navigation.send_velocity(forward_speed=speed, turn_rate_deg=0.0)

    def turn(self, speed: float, turn_rate_deg: float) -> bool:
        """
        Bergerak maju sambil belok.
        turn_rate_deg positif = belok kanan, negatif = belok kiri.
        """
        if self._blocked_by_remote("turn"):
            return False
        return self._navigation.send_velocity(forward_speed=speed, turn_rate_deg=turn_rate_deg)

    def goto(self, lat: float, lon: float) -> bool:
        """
        Memerintahkan kapal berlayar menuju koordinat GPS target.
        Wajib berada di mode GUIDED dan Armed.
        """
        if self._blocked_by_remote("goto"):
            return False
        return self._navigation.goto_target(target_lat=lat, target_lon=lon)

    def stop_movement(self, silent: bool = False) -> bool:
        """
        Menghentikan pergerakan kapal segera (Set kecepatan ke 0).

        TIDAK ikut diblokir saat kendali di remote: perintah ini hanya bisa
        menghentikan, tidak pernah menggerakkan — memblokirnya justru berbahaya.
        """
        return self._navigation.stop(silent=silent)


    # --- SUMBER KENDALI MANUAL (Mini PC vs Remote RC fisik) ---
    # Berapa lama minimal antar log "perintah diabaikan". main.py memanggil
    # send_manual_rc_drive() ~15x/detik walau misi tidak jalan, jadi tanpa throttle ini
    # terminal akan penuh oleh pesan yang sama.
    REMOTE_BLOCK_LOG_INTERVAL_SEC = 5.0

    # Pelepasan override dikirim beberapa kali: satu paket MAVLink bisa hilang di
    # serial, dan paket yang hilang di sini berarti kapal TIDAK bisa dikendalikan
    # remote sama sekali — biaya mengirim ulang jauh lebih murah daripada risikonya.
    RELEASE_REPEAT = 3
    RELEASE_INTERVAL_SEC = 0.1

    def get_manual_source(self) -> str:
        """Sumber kendali manual yang sedang aktif: 'minipc' atau 'remote'."""
        with self._manual_source_lock:
            return self._manual_source

    def minipc_has_control(self) -> bool:
        """True kalau mini PC masih boleh mengirim perintah gerak ke kapal."""
        return self.get_manual_source() == manual_source.MINIPC

    def set_manual_source(self, source: str) -> bool:
        """
        Pindahkan sumber kendali manual antara mini PC dan remote RC fisik.

        source = 'remote':
            1. Gerbang blokir dinyalakan LEBIH DULU, supaya thread kamera/misi yang
               berjalan paralel tidak sempat mengirim override baru di sela-sela
               langkah berikutnya (main.py mengirim tiap frame, ~15x/detik).
            2. Baru kemudian override yang sedang aktif dilepaskan (semua channel = 0).
            Urutan ini WAJIB. Kebalikannya menghasilkan race: override terlepas sesaat,
            lalu frame berikutnya langsung merebutnya kembali dan remote tetap mati.

        source = 'minipc':
            Gerbang dibuka lagi. Kapal TIDAK langsung bergerak — mini PC baru mengambil
            alih saat misi di-start atau joystick base station digerakkan.

        Return False kalau `source` tidak dikenal (lihat manual_source.normalize()).
        """
        target = manual_source.normalize(source)
        if target is None:
            print(f"[ASVController] ⚠️ Sumber kendali '{source}' tidak dikenal — "
                  f"pilih 'minipc' atau 'remote'. Tidak ada yang diubah.")
            return False

        with self._manual_source_lock:
            previous = self._manual_source
            self._manual_source = target   # (1) tutup gerbang dulu

        if target == manual_source.REMOTE:
            released = self._release_to_remote()   # (2) baru lepaskan override
            print(f"[ASVController] 🎮 Kendali manual → {manual_source.label(target)} "
                  f"(override RC {'dilepaskan' if released else 'GAGAL dilepaskan'}).")
            if not released:
                print("[ASVController] ⚠️ Pelepasan eksplisit gagal — kendali tetap akan "
                      "jatuh ke remote setelah RC_OVERRIDE_TIME ArduPilot (default 3 detik) "
                      "karena mini PC sudah berhenti mengirim override.")
        elif previous != target:
            print(f"[ASVController] 🖥️ Kendali manual → {manual_source.label(target)}.")
        return True

    def _release_to_remote(self) -> bool:
        """Kirim pelepasan override berulang kali. True kalau minimal satu berhasil."""
        ok = False
        for i in range(self.RELEASE_REPEAT):
            if self._motion.release_all_rc(verbose=(i == 0)):
                ok = True
            if i < self.RELEASE_REPEAT - 1:
                time.sleep(self.RELEASE_INTERVAL_SEC)
        return ok

    def _blocked_by_remote(self, what: str) -> bool:
        """
        True kalau perintah gerak `what` harus DIBLOKIR karena kendali ada di remote.

        Gerbang ini sengaja dipasang di facade (bukan di tiap modul control/), supaya
        satu pun jalur pengiriman tidak ada yang terlewat — termasuk main.py yang
        mengirim netral (0,0) tiap frame saat misi idle. Netral pun tetap sebuah
        override: kalau lolos, remote fisik ikut terkunci.
        """
        if self.minipc_has_control():
            return False
        now = time.time()
        if now - self._remote_block_last_log >= self.REMOTE_BLOCK_LOG_INTERVAL_SEC:
            self._remote_block_last_log = now
            print(f"[ASVController] 🎮 Kendali di REMOTE RC — perintah '{what}' "
                  f"dari mini PC diabaikan.")
        return True

    # --- KENDALI MANUAL / JOYSTICK (TELEOPERATION) ---
    def send_rc_override(self, channels: list) -> bool:
        """
        Mengirim override PWM langsung ke motor/servo kapal (1000 - 2000 µs, 0/65535 = lepaskan).
        Contoh: send_rc_override([1500, 0, 1600]) -> Steering netral (1500), Throttle maju (1600)
        """
        if self._blocked_by_remote("send_rc_override"):
            return False
        return self._motion.send_rc_override(channels)

    def send_manual_control(self, x: int = 0, y: int = 0, z: int = 500, r: int = 0, buttons: int = 0) -> bool:
        """
        Mengirim pesan MANUAL_CONTROL MAVLink dari Joystick/Gamepad.
        x: Throttle (-1000..1000), y: Steering (-1000..1000), z: Thrust (0..1000), r: Yaw (-1000..1000)
        """
        if self._blocked_by_remote("send_manual_control"):
            return False
        return self._motion.send_manual_control(x, y, z, r, buttons)

    def release_rc(self) -> bool:
        """
        Melepaskan semua override RC (tingkat rendah) agar kendali kembali ke autopilot
        atau remote RC fisik. Dipakai MissionEngine sebelum step GUIDED.

        SENGAJA tidak mengubah sumber kendali manual: fungsi ini tidak pernah
        menggerakkan kapal, dan MissionEngine memanggilnya di tengah misi yang sah.
        Untuk menyerahkan kendali ke operator remote, pakai set_manual_source('remote')
        yang juga memasang gerbang blokir.
        """
        return self._motion.release_all_rc()

    def send_manual_rc_drive(self, steering_norm: float, throttle_norm: float) -> bool:
        """
        Mengirim sinyal kemudi (Ch 1) & throttle (Ch 3) langsung ke Pixhawk via MAVLink RC Override (MANUAL Mode).
        - steering_norm: -1.0 (Belok Kiri 1000us) s/d +1.0 (Belok Kanan 2000us), 0.0 = Netral (1500us)
        - throttle_norm: 0.0 (Stop 1000us) s/d 1.0 (Full Forward 2000us)
        """
        if self._blocked_by_remote("send_manual_rc_drive"):
            return False
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
