import threading
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any

@dataclass
class ASVStateData:
    # Status Koneksi & Sistem
    is_connected: bool = False
    is_armed: bool = False
    mode: str = "UNKNOWN"
    system_status: int = 0
    last_heartbeat: float = 0.0
    
    # Posisi & Navigasi (GPS)
    lat: float = 0.0          # Derajat (contoh: -6.123456)
    lon: float = 0.0          # Derajat (contoh: 106.123456)
    alt: float = 0.0          # Meter di atas permukaan laut
    heading: float = 0.0      # Derajat kompas (0 - 360)
    ground_speed: float = 0.0 # m/s
    vx: float = 0.0           # Kecepatan maju m/s (relatif bumi/utara)
    vy: float = 0.0           # Kecepatan lateral m/s (relatif bumi/timur)
    vz: float = 0.0           # Kecepatan vertikal m/s (relatif bumi/bawah)
    
    # Attitude (Orientasi Kapal)
    roll: float = 0.0         # Derajat (-180 sampai 180)
    pitch: float = 0.0        # Derajat (-180 sampai 180)
    yaw: float = 0.0          # Derajat (0 sampai 360)
    
    # Baterai & Daya
    battery_voltage: float = 0.0    # Volt (e.g., 12.6V)
    battery_current: float = 0.0    # Ampere (e.g., 5.2A)
    battery_remaining: int = 0      # Persentase (0 - 100%)
    
    # Pesan status / log terakhir dari Pixhawk
    status_text: List[str] = field(default_factory=list)


class ASVState:
    """
    Thread-safe container untuk status dan telemetri kapal ASV.
    Diakses serentak oleh MAVLink reader loop (penulis) dan Backend API (pembaca).
    """
    def __init__(self):
        self._data = ASVStateData()
        self._lock = threading.RLock()
        self.max_status_messages = 10
        self._statustext_callback = None

    def set_statustext_callback(self, callback):
        """Register callback yang dipanggil setiap ada STATUSTEXT baru dari FC."""
        self._statustext_callback = callback

    def update_heartbeat(self, is_armed: bool, mode: str, system_status: int):
        with self._lock:
            self._data.is_connected = True
            self._data.is_armed = is_armed
            if mode != "UNKNOWN":
                self._data.mode = mode
            self._data.system_status = system_status
            self._data.last_heartbeat = time.time()

    def update_gps(self, lat: float, lon: float, alt: float, heading: float, ground_speed: float, vx: float = 0.0, vy: float = 0.0, vz: float = 0.0):
        with self._lock:
            self._data.lat = lat
            self._data.lon = lon
            self._data.alt = alt
            if heading >= 0:
                self._data.heading = heading
            self._data.ground_speed = ground_speed
            self._data.vx = vx
            self._data.vy = vy
            self._data.vz = vz

    def update_attitude(self, roll: float, pitch: float, yaw: float):
        with self._lock:
            self._data.roll = roll
            self._data.pitch = pitch
            self._data.yaw = yaw

    def update_battery(self, voltage: float, current: float, remaining: int):
        with self._lock:
            self._data.battery_voltage = voltage
            self._data.battery_current = current
            self._data.battery_remaining = remaining

    def add_status_text(self, text: str):
        with self._lock:
            if not text:
                return
            timestamped = f"[{time.strftime('%H:%M:%S')}] {text}"
            self._data.status_text.append(timestamped)
            if len(self._data.status_text) > self.max_status_messages:
                self._data.status_text.pop(0)
        # Panggil callback di luar lock untuk menghindari deadlock
        if self._statustext_callback:
            try:
                self._statustext_callback(text)
            except Exception:
                pass

    def set_disconnected(self):
        with self._lock:
            self._data.is_connected = False

    def get_data(self) -> ASVStateData:
        """Mengembalikan salinan dari data status saat ini."""
        with self._lock:
            # Mengecek apakah heartbeat sudah terlalu lama tidak diterima (> 5 detik)
            if time.time() - self._data.last_heartbeat > 5.0 and self._data.is_connected:
                self._data.is_connected = False
            return self._data

    def to_dict(self) -> Dict[str, Any]:
        """Mengembalikan data dalam bentuk dictionary agar mudah di-serialize ke JSON oleh backend."""
        with self._lock:
            data = self.get_data()
            return asdict(data)
