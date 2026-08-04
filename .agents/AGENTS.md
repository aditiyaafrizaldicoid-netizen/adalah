# PROJECT ARCHITECTURE & DESIGN DIRECTIVES

## System Concept: Companion Computer (Jetson) + Autopilot (Pixhawk / ArduRover 4.7.x)

```
Camera
  │
  ▼
Vision AI (YOLO / OpenCV)
  │
  ▼
Navigation Planner
  │
  ▼
Mission Logic
  │
  ▼
MAVLink Interface (pymavlink)
  │
  ▼
ArduPilot Rover (Guided Mode)
  │
  ▼
Pixhawk (Internal PID Steering/Throttle/Rudder Controllers)
  │
  ▼
Motors & Rudder Output
```

---

## Strict Rules & Constraints

1. **NO DIRECT MOTOR/SERVO CONTROL**:
   - Companion Computer (Jetson) MUST NEVER send direct PWM, ESC, or Servo Override commands (`rc_override`, `do_set_servo`).
   - All motor mixing, PID steering, PID throttle, and rudder control MUST be handled strictly by ArduPilot internal controllers.

2. **COMPANION COMPUTER ROLE**:
   - High-level intelligence, Vision AI inference, Gate midpoint calculation, Navigation Target generation.
   - Companion Computer is the **Decision Maker**, NOT the Flight Controller.

3. **ARDUPILOT ROLE**:
   - Autopilot in **GUIDED Mode**.
   - Receives target velocity (`SET_POSITION_TARGET_LOCAL_NED`) or target coordinates (`SET_POSITION_TARGET_GLOBAL_INT`) via MAVLink in real-time.
   - Executes tuned ArduRover PIDs to achieve target speed and heading.

4. **CLEAN ARCHITECTURE SEPARATION**:
   - Separate Vision AI, Navigation Planner, Mission Logic, and MAVLink Communication cleanly without mixing concerns.
