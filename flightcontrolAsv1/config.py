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
    - Thruster Kiri & Kanan: SERVOx_FUNCTION = 73 (ThrottleLeft) / 74 (ThrottleRight)
    - Servo Kemudi: SERVOx_FUNCTION = 26 (GroundSteering)
    """
    # --- THRUSTER ---

    thruster_left_ch: int = int(os.getenv("CH_THRUSTER_LEFT", "1"))    # Default MAIN 1 (Thruster Left)
    thruster_right_ch: int = int(os.getenv("CH_THRUSTER_RIGHT", "2"))  # Default MAIN 2 (Thruster Right)

    # --- SERVO (Vectored Thrust / Kemudi) ---
    servo_left_ch: int = int(os.getenv("CH_SERVO_LEFT", "3"))          # Default MAIN 3 (GroundSteering)
    servo_right_ch: int = int(os.getenv("CH_SERVO_RIGHT", "4"))        # Default MAIN 4 (GroundSteering)

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
        print(f"[ChannelConfig] Updated: {self.to_dict()}")



@dataclass
class ASVConfig:
    CONNECTION_STRING: str = os.getenv("ASV_CONNECTION_STRING", "/dev/ttyACM0")
    BAUDRATE: int = int(os.getenv("ASV_BAUDRATE", "115200")) 

    TARGET_SYSTEM: int = int(os.getenv("ASV_TARGET_SYSTEM", "1"))
    TARGET_COMPONENT: int = int(os.getenv("ASV_TARGET_COMPONENT", "1"))
    
    HEARTBEAT_TIMEOUT: float = float(os.getenv("ASV_HEARTBEAT_TIMEOUT", "5.0"))
    RECONNECT_INTERVAL: float = float(os.getenv("ASV_RECONNECT_INTERVAL", "3.0"))
    STREAM_RATE_HZ: int = int(os.getenv("ASV_STREAM_RATE_HZ", "10"))


config = ASVConfig()
channel_config = ChannelConfig()

