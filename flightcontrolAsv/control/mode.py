from pymavlink import mavutil
from connection.manager import ConnectionManager

class ModeControl:
    """
    Daftar mode umum untuk ASV / Rover (ArduBoat / ArduRover):
    - MANUAL  : Kontrol RC langsung (maju/belok sesuai joystick)
    - HOLD    : Kapal diam / stop motor
    - LOITER  : Kapal berusaha mempertahankan posisinya (Virtual Anchor)
    - GUIDED  : Kapal bergerak sesuai perintah kecepatan/posisi dari Mini PC
    - AUTO    : Kapal menjalankan misi waypoint yang sudah diupload
    - RTL     : Return to Launch (kembali ke titik awal)
    """
    def __init__(self, connection: ConnectionManager):
        self.connection = connection

    def set_mode(self, mode_name: str) -> bool:
        """
        Mengubah mode kapal. Contoh: set_mode("GUIDED") atau set_mode("MANUAL")
        """
        mode_name_upper = mode_name.upper()
        if not self.connection.master:
            print("[ModeControl] Gagal ganti mode: Tidak ada koneksi ke Pixhawk.")
            return False

        # Coba ambil ID mode dari mode_mapping pymavlink
        mode_mapping = self.connection.master.mode_mapping()
        if not mode_mapping or mode_name_upper not in mode_mapping:
            # Fallback untuk ArduRover / ArduBoat standar
            default_rover_modes = {
                "MANUAL": 0,
                "ACRO": 1,
                "STEERING": 3,
                "HOLD": 4,
                "LOITER": 5,
                "FOLLOW": 6,
                "SIMPLE": 7,
                "AUTO": 10,
                "RTL": 11,
                "SMART_RTL": 12,
                "GUIDED": 15,
            }
            if mode_name_upper not in default_rover_modes:
                print(f"[ModeControl] Mode '{mode_name}' tidak dikenal untuk kapal/rover ini.")
                return False
            mode_id = default_rover_modes[mode_name_upper]
        else:
            mode_id = mode_mapping[mode_name_upper]

        print(f"[ModeControl] Mengirim perintah ganti mode ke: {mode_name_upper} (ID: {mode_id})")
        
        # Kirim perintah SET_MODE atau MAV_CMD_DO_SET_MODE
        # Untuk ArduPilot, COMMAND_LONG dengan MAV_CMD_DO_SET_MODE adalah yang paling handal
        return self.connection.send_command_long(
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_id
        )
