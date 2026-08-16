import os
import csv
import time

class TelemetryLogger:
    """
    Perekam Blackbox Telemetri Penerbangan ASV (CSV Logger).
    Merekam posisi GPS, kecepatan, heading, mode penerbangan, dan error tracking AI ke file log.
    """

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir, exist_ok=True)

        filename = f"asv_flight_log_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        self.filepath = os.path.join(self.log_dir, filename)

        self._file = open(self.filepath, mode="w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        # Write CSV Header
        self._writer.writerow([
            "timestamp", "iso_time", "mode", "armed", "lat", "lng",
            "heading", "sog_knots", "battery_v", "state", "gate_x", "error_px"
        ])
        self._file.flush()
        print(f"[TelemetryLogger] Blackbox logging started at: {self.filepath}")

    def log_record(self, telemetry: dict, state: str = "IDLE", gate_x: int = None, error_px: int = None):
        """
        Menulis satu entri log telemetri ke CSV file.
        """
        try:
            now = time.time()
            iso_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
            mode = telemetry.get("mode", "UNKNOWN")
            armed = telemetry.get("is_armed", False)
            lat = telemetry.get("lat", 0.0)
            lng = telemetry.get("lon", 0.0)
            heading = telemetry.get("heading", 0.0)
            sog = telemetry.get("sog", 0.0)
            battery_v = telemetry.get("battery_volt", 0.0)

            self._writer.writerow([
                f"{now:.3f}", iso_time, mode, armed, lat, lng,
                heading, sog, battery_v, state, gate_x if gate_x is not None else "", error_px if error_px is not None else ""
            ])
            self._file.flush()
        except Exception as e:
            print(f"[TelemetryLogger] Error writing log record: {e}")

    def close(self):
        """Menutup file log CSV saat script selesai."""
        try:
            if self._file and not self._file.closed:
                self._file.close()
                print(f"[TelemetryLogger] Flight log closed cleanly: {self.filepath}")
        except Exception as e:
            print(f"[TelemetryLogger] Error closing file: {e}")
