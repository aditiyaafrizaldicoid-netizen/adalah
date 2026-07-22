from simple_pid import PID
import time

class TrackingController:
    def __init__(self, frame_width=640, kp=0.5, ki=0.0, kd=0.1):
        """
        Initializes the PID tracking controller.
        :param frame_width: Width of the camera frame (used to find the center).
        :param kp: Proportional gain.
        :param ki: Integral gain.
        :param kd: Derivative gain.
        """
        self.frame_width = frame_width
        self.center_x = frame_width // 2
        
        # PID controller setup
        # We want the ball center_x to match frame center_x, so setpoint is frame center
        self.pid = PID(kp, ki, kd, setpoint=self.center_x)
        
        # We limit the output to reasonable PWM changes.
        # Let's say max steering deviation is +/- 500 from center (1500) -> 1000 to 2000
        self.pid.output_limits = (-500, 500)
        self.last_seen_time = 0

    def compute_steering(self, ball_x):
        """
        Computes the PWM steering value needed to center the ball.
        :param ball_x: X-coordinate of the detected ball center.
        :return: (steering_pwm, is_tracking)
        """
        if ball_x is not None:
            self.last_seen_time = time.time()
            
            # Since PID computes (Setpoint - Process Value) or (Process Value - Setpoint)
            # By default simple_pid calculates error = setpoint - input
            # If ball is to the left (ball_x < center_x), error is positive -> turn left?
            # If we want output to add to 1500:
            # PWM 1000 = left, PWM 1500 = center, PWM 2000 = right
            # If ball_x > center_x (ball is on right), we want PWM > 1500 (turn right).
            # We will feed ball_x to PID. If ball_x > center_x, error = center_x - ball_x (negative).
            # Wait, let's reverse the sign manually to be sure.
            
            error = ball_x - self.center_x 
            # If ball_x > center, error is positive. We want positive output to increase PWM (turn right).
            
            # Update PID with negated error because by default simple_pid does (setpoint - input)
            # So if we feed ball_x as input, it does (center_x - ball_x). 
            # If ball is on right (ball_x > center_x), output is negative.
            # We want positive. So we can just invert the output.
            control_output = -self.pid(ball_x)
            
            steering_pwm = int(1500 + control_output)
            return steering_pwm, True
        else:
            # If ball is lost for a short time, maybe hold last command?
            # For now, return to center if no ball is seen
            if time.time() - self.last_seen_time > 1.0: # Lost for more than 1 second
                return 1500, False
            else:
                return None, False # Indicate no change
