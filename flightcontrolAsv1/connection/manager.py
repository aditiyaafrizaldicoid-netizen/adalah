import threading
import time
from pymavlink import mavutil
from config import ASVConfig
from core.state import ASVState
from connection.parser import MAVLinkParser


class ConnectionManager:
    """
    Mengelola koneksi fisik/jaringan ke Pixhawk menggunakan pymavlink.
    Menjalankan background thread untuk membaca telemetri secara kontinyu
    dan menangani auto-reconnect jika koneksi terputus.
    """
    def __init__(self, config: ASVConfig, state: ASVState):
        self.config = config
        self.state = state
        self.parser = MAVLinkParser(state)
        
        self.master = None
        self._write_lock = threading.Lock()
        self._is_running = False
        self._thread = None
        self._heartbeat_thread = None

    def start(self):
        """Memulai background thread untuk koneksi dan pembacaan pesan MAVLink."""
        if self._is_running:
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._connection_loop, daemon=True, name="MAVLinkConnectionThread")
        self._thread.start()
        
        # Mulai thread penghantar heartbeat (keep-alive) ke Pixhawk
        self._heartbeat_thread = threading.Thread(target=self._send_heartbeat_loop, daemon=True, name="MAVHeartbeatThread")
        self._heartbeat_thread.start()

    def stop(self):
        """Menghentikan background thread dan menutup koneksi."""
        self._is_running = False
        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=1.0)
            except Exception:
                pass
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            try:
                self._heartbeat_thread.join(timeout=1.0)
            except Exception:
                pass
        self._close_connection()

    def send_message(self, msg) -> bool:
        """
        Mengirim pesan MAVLink ke Pixhawk secara thread-safe.
        Return True jika berhasil dikirim.
        """
        with self._write_lock:
            if not self.master or not self.state.get_data().is_connected:
                return False
            try:
                self.master.mav.send(msg)
                return True
            except Exception as e:
                print(f"[ConnectionManager] Error mengirim pesan MAVLink: {e}")
                return False

    def send_command_long(self, command: int, param1=0, param2=0, param3=0, param4=0, param5=0, param6=0, param7=0) -> bool:
        """
        Helper untuk mengirim perintah standar MAV_CMD (COMMAND_LONG).
        """
        with self._write_lock:
            if not self.master or not self.state.get_data().is_connected:
                return False
            try:
                self.master.mav.command_long_send(
                    self.config.TARGET_SYSTEM,
                    self.config.TARGET_COMPONENT,
                    command,
                    0,  # confirmation
                    param1, param2, param3, param4, param5, param6, param7
                )
                return True
            except Exception as e:
                print(f"[ConnectionManager] Error COMMAND_LONG ({command}): {e}")
                return False

    def send_param_set(self, param_name: str, value: float, param_type: int = None) -> bool:
        """
        Mengubah parameter ArduPilot secara langsung via MAVLink PARAM_SET.
        Ekuivalen dengan mengubah parameter di Mission Planner / QGC.

        :param param_name: Nama parameter, misal 'FS_THR_ENABLE', 'ARMING_CHECK'
        :param value: Nilai baru parameter
        :param param_type: Tipe MAVLink (default: MAV_PARAM_TYPE_REAL32)
        """
        with self._write_lock:
            if not self.master or not self.state.get_data().is_connected:
                print(f"[ConnectionManager] PARAM_SET gagal: tidak terhubung ke Pixhawk")
                return False
            if param_type is None:
                param_type = mavutil.mavlink.MAV_PARAM_TYPE_REAL32
            # Nama parameter harus bytes, max 16 karakter
            param_id = param_name.encode('utf-8')[:16]
            try:
                self.master.mav.param_set_send(
                    self.config.TARGET_SYSTEM,
                    self.config.TARGET_COMPONENT,
                    param_id,
                    float(value),
                    param_type
                )
                print(f"[ConnectionManager] PARAM_SET: {param_name} = {value}")
                return True
            except Exception as e:
                print(f"[ConnectionManager] Error PARAM_SET ({param_name}): {e}")
                return False

    def _send_heartbeat_loop(self):
        """Mengirimkan heartbeat periodik (keep-alive) ke Pixhawk setiap 1 detik."""
        while self._is_running:
            if self.master and self.state.get_data().is_connected:
                try:
                    with self._write_lock:
                        self.master.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_GCS,              # Tipe: Ground Control Station / Companion PC
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,     # Autopilot: Invalid (karena kita adalah GCS)
                            0, 0, 0
                        )
                except Exception:
                    pass
            time.sleep(1.0)

    def _connection_loop(self):
        """Loop utama background thread untuk auto-connect dan read telemetri."""
        while self._is_running:
            if self.master is None:
                self._connect()
                if self.master is None:
                    # Gagal connect, tunggu sebelum coba lagi
                    time.sleep(self.config.RECONNECT_INTERVAL)
                    continue
            
            # Membaca pesan masuk
            try:
                msg = self.master.recv_match(blocking=True, timeout=0.5)
                if msg and msg.get_type() != 'BAD_DATA':
                    self.parser.parse_message(msg)
                else:
                    # Cek apakah kehilangan koneksi / heartbeat timeout (> 10 detik tidak ada heartbeat)
                    if self.state.get_data().is_connected and time.time() - self.state.get_data().last_heartbeat > 10.0:
                        print("[ConnectionManager] Heartbeat timeout! Memutus koneksi untuk reconnect...")
                        self.state.set_disconnected()
                        self._close_connection()
            except Exception as e:
                if self._is_running:
                    print(f"[ConnectionManager] Read error: {e}. Mencoba sambung ulang...")
                self.state.set_disconnected()
                self._close_connection()
                time.sleep(self.config.RECONNECT_INTERVAL)

    def _connect(self):
        print(f"[ConnectionManager] Mencoba membuka koneksi ke {self.config.CONNECTION_STRING} (baud={self.config.BAUDRATE})...")
        try:
            self.master = mavutil.mavlink_connection(
                self.config.CONNECTION_STRING,
                baud=self.config.BAUDRATE,
                source_system=255,  # 255 = GCS / Companion Computer ID standar
            )
            # Menunggu heartbeat pertama dari Pixhawk (maksimal 10 detik)
            print("[ConnectionManager] Menunggu heartbeat dari Pixhawk...")
            hb = self.master.wait_heartbeat(timeout=10.0)
            if not hb:
                print("[ConnectionManager] Gagal menerima heartbeat pertama (Timeout).")
                self._close_connection()
                return

            print(f"[ConnectionManager] Terhubung ke Pixhawk! (System ID: {self.master.target_system}, Component ID: {self.master.target_component})")
            
            # Sinkronisasi parameter target
            self.config.TARGET_SYSTEM = self.master.target_system
            self.config.TARGET_COMPONENT = self.master.target_component
            
            # Update parser dengan heartbeat pertama
            self.parser.parse_message(hb)
            
            # Meminta Pixhawk untuk memancarkan semua stream telemetri secara berkala
            self._request_data_streams()

        except Exception as e:
            print(f"[ConnectionManager] Gagal koneksi ke {self.config.CONNECTION_STRING}: {e}")
            self._close_connection()

    def _close_connection(self):
        if self.master:
            try:
                self.master.close()
            except Exception:
                pass
            self.master = None

    def _request_data_streams(self):
        """Meminta Pixhawk (ArduPilot/PX4) memancarkan data GPS, Attitude, RC, dan Baterai."""
        try:
            # Request all streams dengan frekuensi STREAM_RATE_HZ dari config
            self.master.mav.request_data_stream_send(
                self.config.TARGET_SYSTEM,
                self.config.TARGET_COMPONENT,
                mavutil.mavlink.MAV_DATA_STREAM_ALL,
                self.config.STREAM_RATE_HZ,
                1  # 1 = Start streaming
            )
            print(f"[ConnectionManager] Berhasil meminta stream telemetri ({self.config.STREAM_RATE_HZ} Hz)")
        except Exception as e:
            print(f"[ConnectionManager] Gagal meminta data stream: {e}")

    def _send_heartbeat_loop(self):
        """Pancar MAVLink Heartbeat (1 Hz) dari Companion Computer ke Pixhawk."""
        while self._is_running:
            if self.master and self.state.get_data().is_connected:
                try:
                    with self._write_lock:
                        self.master.mav.heartbeat_send(
                            mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                            0, 0, 0
                        )
                except Exception:
                    pass
            time.sleep(1.0)

