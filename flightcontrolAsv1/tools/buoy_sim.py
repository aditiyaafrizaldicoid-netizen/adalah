#!/usr/bin/env python3
"""
buoy_sim.py — Simulator ringan untuk menguji tracking buoy TANPA kapal & tanpa air.

Menjalankan MissionEngine + TrackingController YANG ASLI (bukan tiruan), dengan
kamera & gerak kapal yang disimulasikan. Dipakai untuk:
  - Tuning Kp tanpa harus turun ke danau
  - Menghitung berapa kali kapal MENABRAK buoy pada satu set gain
  - Melihat berapa persen frame kemudinya MENTOK (penyebab bang-bang steering)

KENAPA BUKAN GAZEBO: yang perlu divalidasi di sini adalah loop kontrol dan logika
anti-tabrak — itu tidak butuh physics engine, air, atau rendering. Bug gain kemudi
yang membuat kapal terus menabrak ditemukan lewat simulasi numerik sederhana
seperti ini. Gazebo juga TIDAK menyelesaikan bagian tersulit (deteksi YOLO), karena
buoy hasil render berbeda dari buoy asli tempat model dilatih.

BATASAN YANG HARUS DIINGAT (jangan diperlakukan sebagai bukti lapangan):
  - Model gerak kapal di sini kinematik sederhana + lag orde-1, BUKAN hidrodinamika.
  - Tidak ada arus, angin, gelombang.
  - Deteksi buoy dianggap sempurna kecuali noise & dropout yang disuntik manual;
    kegagalan YOLO yang sesungguhnya (silau, pantulan, false positive) tidak
    dimodelkan.
Simulator ini bagus untuk menemukan masalah KONTROL & LOGIKA, bukan untuk
memastikan sesuatu pasti aman di air.

Pemakaian:
    python3 tools/buoy_sim.py                     # jalankan dengan gain dari DB
    python3 tools/buoy_sim.py --kp 0.15           # coba gain lain
    python3 tools/buoy_sim.py --sweep             # bandingkan banyak Kp sekaligus
    python3 tools/buoy_sim.py --kp 0.309 --ki 0.19 --kd 0.683   # config lama
"""

import argparse
import io
import math
import os
import random
import sys
import contextlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from control.pid_tracker import TrackingController
from control.mission_engine import MissionEngine
from vision.gate_convention import LEFT, side_of


# ── Parameter fisik kapal (perkiraan; sesuaikan kalau tahu angka aslinya) ──────
BOAT_HALF_WIDTH_M = 0.35     # setengah lebar lambung — dipakai untuk deteksi tabrakan
BUOY_RADIUS_M     = 0.15     # jari-jari buoy
MAX_YAW_RATE_DPS  = 45.0     # yaw rate saat steer = ±1.0
SPEED_AT_FULL_THR = 2.0      # m/s saat throttle = 1.0
YAW_LAG_TAU_S     = 0.35     # inersia belok (orde-1). 0 = respons instan (tidak realistis)

FPS = 15.0
DT = 1.0 / FPS


class SimBoat:
    def __init__(self, x=0.0, y=0.0, heading_deg=90.0):
        self.x = x
        self.y = y
        self.heading = math.radians(heading_deg)
        self.yaw_rate = 0.0

    def step(self, steer_norm, throttle_norm, dt=DT):
        # steer POSITIF = belok KANAN. Di koordinat dunia standar (x ke kanan,
        # y ke atas, heading diukur berlawanan arah jarum jam), belok kanan berarti
        # heading BERKURANG — karena itu ada tanda minus di sini. Tanpa itu kemudi
        # jadi terbalik dan kapal melenceng ke arah yang salah.
        target_yaw = -math.radians(MAX_YAW_RATE_DPS) * max(-1.0, min(1.0, steer_norm))
        # lag orde-1: kapal tidak bisa berbelok seketika
        if YAW_LAG_TAU_S > 0:
            self.yaw_rate += (target_yaw - self.yaw_rate) * min(1.0, dt / YAW_LAG_TAU_S)
        else:
            self.yaw_rate = target_yaw
        self.heading += self.yaw_rate * dt
        speed = SPEED_AT_FULL_THR * max(0.0, min(1.0, throttle_norm))
        self.x += speed * math.cos(self.heading) * dt
        self.y += speed * math.sin(self.heading) * dt


class SimCamera:
    """Pinhole sederhana: proyeksikan buoy dunia -> koordinat piksel."""

    def __init__(self, width, height, hfov_deg=70.0):
        self.width = width
        self.height = height
        self.center_x = width // 2
        self.f = (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)

    def project(self, boat, bx, by):
        dx, dy = bx - boat.x, by - boat.y
        ct, st = math.cos(boat.heading), math.sin(boat.heading)
        forward = dx * ct + dy * st
        right = dx * st - dy * ct
        if forward <= 0.3:            # di belakang / terlalu dekat bidang kamera
            return None
        px = self.center_x + self.f * (right / forward)
        if px < 0 or px >= self.width:
            return None               # keluar frame
        dist = math.hypot(dx, dy)
        size_px = max(4.0, self.f * (2 * BUOY_RADIUS_M) / max(dist, 0.3))
        return px, self.height / 2.0, size_px, dist


def build_course(n_gates=3, spacing=5.0, gate_width=2.0, curve=0.35):
    """
    Rangkaian gerbang merah/hijau, sedikit melengkung seperti arena di foto.

    Sisi setiap warna diambil dari vision/gate_convention.py — SUMBER YANG SAMA
    dengan yang dipakai kode terbang. Ini disengaja: kalau course di sini ditulis
    dengan sisi yang di-hardcode, simulator bisa memvalidasi arena yang BUKAN arena
    sesungguhnya dan melaporkan "bersih" untuk logika yang di air justru menabrak
    (persis yang terjadi sebelum konvensi ini dipusatkan).
    """
    gates = []
    for i in range(n_gates):
        cy = 6.0 + i * spacing
        cx = curve * (i ** 2)          # melengkung pelan ke kanan
        left_x  = cx - gate_width / 2.0
        right_x = cx + gate_width / 2.0
        gates.append({
            "red":   (left_x if side_of("red") == LEFT else right_x, cy),
            "green": (left_x if side_of("green") == LEFT else right_x, cy),
        })
    return gates


class FakeTelemetry:
    heading = 0.0
    mode = "MANUAL"
    is_armed = True
    lat = 0.0
    lon = 0.0


class FakeASV:
    def is_connected(self): return True
    def get_telemetry(self): return FakeTelemetry()
    def set_mode(self, m): pass
    def stop_movement(self, silent=False): pass
    def send_manual_rc_drive(self, s, t): pass


def run_sim(kp, ki, kd, max_turn, deadzone, width, height,
            jitter_px=6.0, dropout=0.05, seed=1, max_sec=45.0,
            step_cfg=None, verbose=False):
    random.seed(seed)
    quiet = io.StringIO()

    with contextlib.redirect_stdout(quiet):
        ctrl = TrackingController(frame_width=width, kp=kp, ki=ki, kd=kd,
                                  max_turn_rate=max_turn)
    ctrl.align_threshold_px = deadzone
    ctrl.pid.sample_time = None      # jangan lewati frame; kita kontrol dt sendiri

    with contextlib.redirect_stdout(quiet):
        engine = MissionEngine(asv=FakeASV(), tracker=None, tracking_controller=ctrl,
                               camera_width=width, camera_height=height)
        step = {"id": 1, "type": "BUOY_CHASE", "throttle": 0.4}
        if step_cfg:
            step.update(step_cfg)
        engine.start_mission([step, {"id": 2, "type": "FINISH"}])

    cam = SimCamera(width, height)
    boat = SimBoat()
    gates = build_course()

    hits = set()
    steers = []
    path = [(boat.x, boat.y)]
    min_clear = {}

    n_steps = int(max_sec * FPS)
    for _ in range(n_steps):
        detected = {"red": [], "green": []}
        for gi, g in enumerate(gates):
            for side in ("red", "green"):
                bx, by = g[side]
                # jarak terdekat lambung-ke-buoy, untuk deteksi tabrakan
                d = math.hypot(bx - boat.x, by - boat.y)
                key = (gi, side)
                min_clear[key] = min(min_clear.get(key, 1e9), d)
                if d < (BOAT_HALF_WIDTH_M + BUOY_RADIUS_M):
                    hits.add(key)

                p = cam.project(boat, bx, by)
                if p is None:
                    continue
                if random.random() < dropout:      # YOLO sesekali miss
                    continue
                px, py, size, _ = p
                px += random.uniform(-jitter_px, jitter_px)
                half = size / 2.0
                detected[side].append(
                    (int(px), int(py), int(px - half), int(py - half),
                     int(px + half), int(py + half)))

        # urutkan foreground-first, sama seperti vision/tracker.py
        for side in ("red", "green"):
            detected[side].sort(key=lambda b: (b[4] - b[2]) * (b[5] - b[3]), reverse=True)

        with contextlib.redirect_stdout(quiet):
            steer, thr, label = engine.update_frame(None, None, detected)

        steers.append(steer)
        boat.step(steer, thr)
        path.append((boat.x, boat.y))

        if engine.status != "RUNNING" or engine._current_step_idx > 0:
            break
        if boat.y > gates[-1]["red"][1] + 4.0:
            break

    sat = sum(1 for s in steers if abs(s) >= 0.999)
    flips = sum(1 for a, b in zip(steers, steers[1:]) if a * b < 0)
    passed = sum(1 for gi in range(len(gates))
                 if boat.y > gates[gi]["red"][1])
    closest = min(min_clear.values()) if min_clear else float("nan")

    return {
        "hits": len(hits), "gates_passed": passed, "total_gates": len(gates),
        "sat_pct": 100.0 * sat / max(1, len(steers)),
        "flips": flips, "frames": len(steers),
        "closest_m": closest, "path": path, "cleared": engine._seq_pairs_cleared,
    }


def fmt(r):
    verdict = "TABRAK" if r["hits"] else "bersih"
    return (f"tabrakan {r['hits']:>1}  |  gerbang lewat {r['gates_passed']}/{r['total_gates']}"
            f"  |  jarak terdekat {r['closest_m']:.2f}m"
            f"  |  kemudi mentok {r['sat_pct']:>5.1f}%  |  ganti arah {r['flips']:>3}"
            f"  |  {verdict}")


def ascii_plot(path, gates, w=64, h=26):
    xs = [p[0] for p in path] + [g[s][0] for g in gates for s in ("red", "green")]
    ys = [p[1] for p in path] + [g[s][1] for g in gates for s in ("red", "green")]
    x0, x1, y0, y1 = min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1
    grid = [[" "] * w for _ in range(h)]

    def cell(x, y):
        cx = int((x - x0) / max(x1 - x0, 1e-6) * (w - 1))
        cy = int((y - y0) / max(y1 - y0, 1e-6) * (h - 1))
        return cx, h - 1 - cy

    for px, py in path:
        cx, cy = cell(px, py)
        if 0 <= cy < h and 0 <= cx < w:
            grid[cy][cx] = "."
    for g in gates:
        for side, ch in (("red", "R"), ("green", "G")):
            cx, cy = cell(*g[side])
            if 0 <= cy < h and 0 <= cx < w:
                grid[cy][cx] = ch
    return "\n".join("  |" + "".join(row) + "|" for row in grid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kp", type=float, default=None)
    ap.add_argument("--ki", type=float, default=None)
    ap.add_argument("--kd", type=float, default=None)
    ap.add_argument("--max-turn", type=float, default=30.0)
    ap.add_argument("--deadzone", type=float, default=12.0)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=360)
    ap.add_argument("--jitter", type=float, default=6.0)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--runs", type=int, default=5, help="ulangi dgn seed berbeda")
    ap.add_argument("--sweep", action="store_true", help="bandingkan beberapa Kp")
    ap.add_argument("--plot", action="store_true", help="gambar lintasan ASCII")
    args = ap.parse_args()

    kp = args.kp if args.kp is not None else 0.10
    ki = args.ki if args.ki is not None else 0.0
    kd = args.kd if args.kd is not None else 0.0

    print(f"Frame {args.width}x{args.height} | {FPS:.0f} FPS | jitter ±{args.jitter}px "
          f"| dropout {args.dropout*100:.0f}% | {args.runs} run/konfigurasi")
    print(f"Kapal: lebar ±{BOAT_HALF_WIDTH_M*2:.1f}m, yaw max {MAX_YAW_RATE_DPS:.0f}°/s, "
          f"lag {YAW_LAG_TAU_S}s\n")

    def evaluate(k_p, k_i, k_d, label):
        rows = [run_sim(k_p, k_i, k_d, args.max_turn, args.deadzone,
                        args.width, args.height, args.jitter, args.dropout, seed=s)
                for s in range(args.runs)]
        hits = sum(r["hits"] for r in rows)
        sat = sum(r["sat_pct"] for r in rows) / len(rows)
        flips = sum(r["flips"] for r in rows) / len(rows)
        clear = min(r["closest_m"] for r in rows)
        passed = sum(r["gates_passed"] for r in rows)
        total = rows[0]["total_gates"] * len(rows)
        print(f"{label:<34} tabrakan {hits:>2}  lewat {passed:>2}/{total}"
              f"  terdekat {clear:>5.2f}m  mentok {sat:>5.1f}%  flip {flips:>5.1f}")
        return rows

    if args.sweep:
        print("SWEEP — mencari Kp terbaik (Ki=Kd=0):\n")
        evaluate(0.309, 0.1905, 0.683, "config LAMA (Kp.309 Ki.19 Kd.68)")
        print()
        for k in (0.06, 0.08, 0.10, 0.13, 0.16, 0.20, 0.25):
            evaluate(k, 0.0, 0.0, f"Kp={k:.2f}")
    else:
        rows = evaluate(kp, ki, kd, f"Kp={kp} Ki={ki} Kd={kd}")
        if args.plot:
            print("\nLintasan run pertama (R/G = buoy, . = jalur kapal):")
            print(ascii_plot(rows[0]["path"], build_course()))

    print("\nCatatan: ini simulasi kinematik, bukan hidrodinamika — dan deteksi YOLO")
    print("nyata (silau, pantulan, false positive) TIDAK dimodelkan. Gunakan untuk")
    print("menemukan masalah kontrol/logika, bukan sebagai jaminan aman di air.")


if __name__ == "__main__":
    main()
