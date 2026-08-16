import time
from pymavlink import mavutil
from connection.manager import ConnectionManager

class ArmingControl:
    def __init__(self, connection: ConnectionManager):
        self.connection = connection

    def arm(self, force: bool = True) -> bool:
        """
        Mengaktifkan (ARM) motor kapal.
        Jika force=True, mengabaikan pre-arm safety checks dengan magic number ArduPilot 21196.
        """
        print(f"[ArmingControl] Mengirim perintah ARM (force={force})...")
        param2 = 21196 if force else 0  # 21196 adalah magic number ArduPilot untuk force arm
        return self.connection.send_command_long(
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            1,       # 1 = ARM
            param2,  # Force/Override safety checks
        )

    def disarm(self, force: bool = True) -> bool:
        """
        Mematikan (DISARM) motor kapal.
        """
        print(f"[ArmingControl] Mengirim perintah DISARM (force={force})...")
        param2 = 21196 if force else 0  # 21196 adalah magic number untuk force disarm
        return self.connection.send_command_long(
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,       # 0 = DISARM
            param2,
        )
