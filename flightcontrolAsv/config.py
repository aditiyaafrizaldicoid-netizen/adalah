import os
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class ChannelConfig:
    """
    Mapping channel RC Output Pixhawk untuk aktuator kapal ASV.

    Channel 1-8  = MAIN OUT (fisik di konektor MAIN)
    Channel 9-16 = AUX OUT  (fisik di konektor AUX)

    Pastikan di Mission Planner / ArduPilot:
    - MAIN channel yang dipakai thruster: SERVOx_FUNCTION = 70 (Throttle) atau 73/74 (Motor1/Motor2)
    - AUX channel yang dipakai servo: SERVOx_FUNCTION = 0 (Disabled) agar bisa digerakkan via RC Override

    Metode kendali:
    - "rc_override" : Mensimulasikan sinyal RC joystick (DIREKOMENDASIKAN - selalu bisa override)
    - "do_set_servo": Perintah langsung ke servo (bisa DIBLOKIR ArduPilot jika channel sudah di-assign)
    """
    # --- THRUSTER ---
    thruster_left_ch: int = int(os.getenv("CH_THRUSTER_LEFT", "1"))    # Default MAIN 1 (Thruster Left)
    thruster_right_ch: int = int(os.getenv("CH_THRUSTER_RIGHT", "2"))  # Default MAIN 2 (Thruster Right)

    # --- SERVO (Vectored Thrust / Kemudi) ---
    servo_left_ch: int = int(os.getenv("CH_SERVO_LEFT", "3"))          # Default MAIN 3 (GroundSteering)
    servo_right_ch: int = int(os.getenv("CH_SERVO_RIGHT", "4"))        # Default MAIN 4 (GroundSteering)

    # --- Metode pengiriman ---
    servo_method: str = os.getenv("SERVO_METHOD", "rc_override")       # "rc_override" | "do_set_servo"

    def to_dict(self) -> dict:
        return asdict(self)

    def update_from_dict(self, d: dict):
        """Update config dari dict yang dikirim base station."""
        if "thruster_left_ch" in d:
            self.thruster_left_ch = int(d["thruster_left_ch"])
        if "thruster_right_ch" in d:
            self.thruster_right_ch = int(d["thruster_right_ch"])
        if "servo_left_ch" in d:
            self.servo_left_ch = int(d["servo_left_ch"])
        if "servo_right_ch" in d:
            self.servo_right_ch = int(d["servo_right_ch"])
        if "servo_method" in d and d["servo_method"] in ("rc_override", "do_set_servo"):
            self.servo_method = d["servo_method"]
        print(f"[ChannelConfig] Updated: {self.to_dict()}")


@dataclass
class ASVConfig:
    # Koneksi Fisik ke Pixhawk di Mini PC
    # Contoh port Linux USB/ACM: "/dev/ttyACM0" atau "/dev/ttyUSB0"
    # Contoh koneksi via network/SITL: "udp:127.0.0.1:14550" atau "tcp:127.0.0.1:5760"
    CONNECTION_STRING: str = os.getenv("ASV_CONNECTION_STRING", "/dev/ttyACM0")
    BAUDRATE: int = int(os.getenv("ASV_BAUDRATE", "115200"))  # FIX: default 115200

    # Identitas System MAVLink
    TARGET_SYSTEM: int = int(os.getenv("ASV_TARGET_SYSTEM", "1"))
    TARGET_COMPONENT: int = int(os.getenv("ASV_TARGET_COMPONENT", "1"))

    # Timeout & Reconnection (detik)
    HEARTBEAT_TIMEOUT: float = float(os.getenv("ASV_HEARTBEAT_TIMEOUT", "5.0"))
    RECONNECT_INTERVAL: float = float(os.getenv("ASV_RECONNECT_INTERVAL", "3.0"))

    # Interval permintaan stream data (Hz / frequency)
    # Menentukan seberapa cepat Pixhawk mengirimkan telemetri ke Mini PC
    STREAM_RATE_HZ: int = int(os.getenv("ASV_STREAM_RATE_HZ", "10"))


config = ASVConfig()
channel_config = ChannelConfig()

