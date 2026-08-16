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

        # Dapatkan ID mode dari mapping pymavlink atau default ArduRover
        mode_mapping = self.connection.master.mode_mapping()
        default_rover_modes = {
            "MANUAL": 0, "ACRO": 1, "STEERING": 3, "HOLD": 4,
            "LOITER": 5, "FOLLOW": 6, "SIMPLE": 7, "AUTO": 10,
            "RTL": 11, "SMART_RTL": 12, "GUIDED": 15,
        }
        mode_id = (mode_mapping or {}).get(mode_name_upper, default_rover_modes.get(mode_name_upper, 15))

        print(f"[ModeControl] Mengirim perintah ganti mode ke: {mode_name_upper} (ID: {mode_id})")

        try:
            # 1. Pilihan Utama: Gunakan method master.set_mode() bawaan pymavlink
            if hasattr(self.connection.master, 'set_mode'):
                try:
                    self.connection.master.set_mode(mode_name_upper)
                except Exception:
                    self.connection.master.set_mode(mode_id)

            # 2. Kirim pesan MAVLink SET_MODE (Message ID #11)
            self.connection.master.mav.set_mode_send(
                self.connection.config.TARGET_SYSTEM,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id
            )

            # 3. Kirim COMMAND_LONG MAV_CMD_DO_SET_MODE untuk redundansi
            self.connection.send_command_long(
                mavutil.mavlink.MAV_CMD_DO_SET_MODE,
                mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id
            )
            return True
        except Exception as e:
            print(f"[ModeControl] Error ganti mode: {e}")
            return False

