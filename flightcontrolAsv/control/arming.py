import time
from pymavlink import mavutil
from connection.manager import ConnectionManager

class ArmingControl:
    def __init__(self, connection: ConnectionManager):
        self.connection = connection

    def arm(self, force: bool = False) -> bool:
        """
        Mengaktifkan (ARM) motor kapal.
        Jika force=True, akan mengabaikan pre-arm checks (hati-hati!).
        """
        print("[ArmingControl] Mengirim perintah ARM...")
        param2 = 2989 if force else 0 # 2989 adalah magic number ArduPilot untuk force arm
        return self.connection.send_command_long(
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            1,       # 1 = ARM
            param2,  # Force/Override safety checks
        )

    def disarm(self, force: bool = False) -> bool:
        """
        Mematikan (DISARM) motor kapal.
        """
        print("[ArmingControl] Mengirim perintah DISARM...")
        param2 = 21196 if force else 0 # 21196 adalah magic number untuk force disarm
        return self.connection.send_command_long(
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,       # 0 = DISARM
            param2,
        )
