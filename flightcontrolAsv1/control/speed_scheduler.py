"""
Speed Scheduler Module.
Calculates desired forward velocity (m/s) based on desired yaw rate (deg/s).
Enforces low-speed turning for sharp maneuvers and high speed on straight paths.
"""


class SpeedScheduler:
    """
    Speed Scheduler dynamically mapping normalized steering to throttle ratio (0.0 to 1.0).
    Used for manual/RC override control modes.
    """

    def __init__(self, max_base_throttle: float = 0.4):
        """
        :param max_base_throttle: Maximum throttle scale factor (0.0 to 1.0).
        """
        self.max_base_throttle = max_base_throttle

    def update_throttle_limit(self, max_base_throttle: float):
        """
        Update max base throttle scale dynamically (0.01 to 1.0).
        """
        try:
            val = float(max_base_throttle)
            if val > 1.0:
                val = val / 100.0
            self.max_base_throttle = max(0.01, min(1.0, val))
            print(f"[SpeedScheduler] Max Base Throttle scale updated to: {self.max_base_throttle * 100:.0f}% ({self.max_base_throttle:.2f})")
        except Exception as e:
            print(f"[SpeedScheduler] Error updating throttle limit: {e}")

    def compute_throttle(self, steer_norm: float = 0.0, target_present: bool = True) -> float:
        """
        Compute throttle ratio.
        Mengembalikan nilai throttle konstan (max_base_throttle) secara langsung tanpa reduksi bertahap.

        :param steer_norm: Steering ratio between -1.0 and +1.0.
        :param target_present: Flag indicating if target is visible.
        :return: Computed throttle ratio between 0.0 and 1.0.
        """
        if not target_present:
            return 0.0

        return round(self.max_base_throttle, 2)


class YawRateSpeedScheduler:
    """
    Speed Scheduler dynamically mapping desired yaw rate (deg/s) to desired velocity (m/s).
    """

    def __init__(
        self,
        max_velocity: float = 1.2,
        min_velocity: float = 0.3
    ):
        """
        :param max_velocity: Maximum speed (m/s) when moving straight (yaw_rate = 0).
        :param min_velocity: Minimum speed (m/s) during extreme sharp turns.
        """
        self.max_velocity = max_velocity
        self.min_velocity = min_velocity

    def compute_velocity(self, desired_yaw_rate: float) -> float:
        """
        Compute desired forward velocity (m/s) based on desired yaw rate (deg/s).

        Examples mapping:
        - abs(yaw_rate) <= 2.0  -> 1.2 m/s (Straight ahead)
        - abs(yaw_rate) ~ 5.0   -> 1.0 m/s (Mild turn)
        - abs(yaw_rate) ~ 15.0  -> 0.7 m/s (Moderate turn)
        - abs(yaw_rate) >= 25.0 -> 0.4 m/s (Sharp turn)

        :param desired_yaw_rate: Yaw rate in deg/s.
        :return: desired_velocity in m/s.
        """
        abs_yaw_rate = abs(float(desired_yaw_rate))

        if abs_yaw_rate < 2.0:
            velocity = self.max_velocity
        elif abs_yaw_rate < 8.0:
            # Interpolate between 1.2 and 1.0 m/s
            ratio = (abs_yaw_rate - 2.0) / (8.0 - 2.0)
            velocity = 1.2 - ratio * (1.2 - 1.0)
        elif abs_yaw_rate < 20.0:
            # Interpolate between 1.0 and 0.7 m/s
            ratio = (abs_yaw_rate - 8.0) / (20.0 - 8.0)
            velocity = 1.0 - ratio * (1.0 - 0.7)
        elif abs_yaw_rate < 30.0:
            # Interpolate between 0.7 and 0.4 m/s
            ratio = (abs_yaw_rate - 20.0) / (30.0 - 20.0)
            velocity = 0.7 - ratio * (0.7 - 0.4)
        else:
            velocity = self.min_velocity

        # Scale velocity proportionally if user configured custom max_velocity
        scale_factor = self.max_velocity / 1.2
        velocity = velocity * scale_factor

        velocity = max(self.min_velocity, min(self.max_velocity, velocity))

        return round(velocity, 2)

