import math
import threading
import time
from dataclasses import dataclass, field, asdict

# Kecepatan minimum (m/s) agar COG (Course Over Ground) dianggap berarti.
# Di bawah ini, vx/vy dari GPS/EKF didominasi derau: arah hasil atan2-nya melompat
# acak ke segala penjuru walau kapal diam di tempat. Karena itu COG TIDAK dihitung
# ulang saat kapal (nyaris) berhenti — nilai valid terakhir dipertahankan dan
# ditandai tidak-valid, supaya operator tahu angkanya sudah basi alih-alih melihat
# jarum berputar-putar sendiri.
# 0.3 m/s ≈ 0.6 knot — cukup di atas derau, masih jauh di bawah kecepatan jelajah.
COG_MIN_SPEED_MS = 0.3
from typing import List, Dict, Any, Optional

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
    heading: float = 0.0      # Derajat kompas (0 - 360) — arah HALUAN menghadap
    cog: float = 0.0          # Course Over Ground (derajat 0-360) — arah GERAK sesungguhnya
    cog_valid: bool = False   # False = kapal terlalu pelan, `cog` adalah nilai lama
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

    # ── Input RC mentah dari receiver (lewat Pixhawk) ────────────────────────
    # Dipakai untuk membaca posisi switch fisik di remote — mis. SwD pada FS-i6X
    # yang memindahkan sumber kendali. Nilai dalam mikrodetik (±1000-2000);
    # 0 atau 65535 berarti channel itu tidak tersedia.
    rc_channels: List[int] = field(default_factory=list)
    rc_rssi: int = 0            # 0 = tidak ada sinyal, 255 = tidak diketahui
    rc_last_update: float = 0.0  # time.time() paket RC terakhir; 0 = belum pernah


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

            # COG diturunkan dari vektor kecepatan bumi (frame NED: vx = ke UTARA,
            # vy = ke TIMUR), BUKAN dari kompas. Bedanya dengan heading itulah yang
            # menunjukkan kapal sedang dihanyutkan arus/angin: haluan menghadap ke
            # satu arah, jalannya ke arah lain.
            if ground_speed >= COG_MIN_SPEED_MS:
                self._data.cog = math.degrees(math.atan2(vy, vx)) % 360.0
                self._data.cog_valid = True
            else:
                # Terlalu pelan untuk dipercaya — pertahankan nilai terakhir, tandai basi.
                self._data.cog_valid = False

    def update_rc_channels(self, channels: List[int], rssi: int = 255):
        """Simpan nilai channel RC mentah dari receiver (via Pixhawk)."""
        with self._lock:
            self._data.rc_channels = list(channels)
            self._data.rc_rssi = int(rssi)
            self._data.rc_last_update = time.time()

    def get_rc_channel(self, channel: int) -> Optional[int]:
        """
        Nilai PWM satu channel RC (1-indexed), atau None kalau tidak tersedia.

        None dikembalikan — bukan 0 atau nilai tengah — supaya pemanggil bisa
        membedakan "channel tidak terbaca" dari "channel bernilai rendah". Menebak
        nilai di sini berarti posisi switch bisa salah dibaca, dan itu menentukan
        siapa yang memegang kemudi kapal.
        """
        with self._lock:
            ch = self._data.rc_channels
            if channel < 1 or channel > len(ch):
                return None
            nilai = ch[channel - 1]
            # 0 dan 65535 adalah penanda "tidak tersedia" di MAVLink, bukan PWM.
            if nilai in (0, 65535):
                return None
            return int(nilai)

    def rc_link_fresh(self, max_age_sec: float) -> bool:
        """Apakah paket RC terakhir masih cukup baru untuk dipercaya."""
        with self._lock:
            if self._data.rc_last_update <= 0:
                return False
            return (time.time() - self._data.rc_last_update) <= max_age_sec

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
