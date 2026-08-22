"""
Utilitas pairing bola (merah + hijau) menjadi pasangan gate, berdasarkan jarak
terdekat ke kamera (area bounding box) dan kemiripan area (jarak fisik) antar bola.

Dipakai bersama oleh:
  - control/mission_engine.py : menentukan pasangan gate mana yang dikunci untuk
    navigasi (SEQUENTIAL_BUOY).
  - vision/tracker.py         : menomori bola di OSD video (1, 2, 3, 4, ...) supaya
    operator bisa memverifikasi SECARA VISUAL bahwa pasangan yang dipakai sistem
    untuk menghitung titik tengah (center point) navigasi sudah benar.

Modul ini sengaja dipisah dari kedua file di atas (bukan milik salah satunya) agar
TIDAK ada dependency silang antara paket `control` dan `vision` — keduanya sama-sama
boleh mengimpor modul murni/stateless ini tanpa saling bergantung satu sama lain.
"""

import math
from typing import List, Tuple

# Tuple (cx, cy, x1, y1, x2, y2) — format deteksi bola yang dipakai di seluruh codebase.
Ball = Tuple[int, int, int, int, int, int]


def bbox_area(ball: Ball) -> float:
    """Area bounding box (piksel²) dari tuple (cx, cy, x1, y1, x2, y2)."""
    return float((ball[4] - ball[2]) * (ball[5] - ball[3]))


def sort_ball_pairs(
    red_balls: List[Ball],
    green_balls: List[Ball],
    min_area_ratio: float = 0.35,
    max_pairs: int = 3,
) -> List[Tuple[Ball, Ball]]:
    """
    Urutkan & pasangkan bola merah-hijau menjadi pasangan gate, terdekat ke kamera
    dahulu (area bbox terbesar = terdekat).

    Algoritma:
      1. Sort bola merah & hijau masing-masing berdasarkan area bbox (terbesar dulu).
      2. Greedy matching: untuk tiap bola merah (urut terdekat → terjauh), cari bola
         hijau BELUM DIPAKAI dengan jarak piksel terdekat.
      3. Tolak kandidat pasangan yang rasio area-nya (min/max) < min_area_ratio — dua
         bola dari gate yang sama berjarak kurang-lebih sama dari kamera sehingga
         area bbox-nya mirip; rasio yang timpang menandakan kedua bola kemungkinan
         besar berasal dari gate/jarak yang BERBEDA (mis. bola sisa gate sebelumnya
         yang kebetulan dekat secara piksel dengan bola gate berikutnya).
      4. Sort akhir pasangan berdasarkan rata-rata area (terbesar = terdekat = Pasangan 1).

    Returns:
        List (red_ball, green_ball), urut dari pasangan terdekat ke terjauh.
        Maksimum `max_pairs` pasangan. List kosong jika salah satu warna tidak ada
        bola sama sekali, atau tidak ada kandidat pasangan yang lolos filter area.
    """
    if not red_balls or not green_balls:
        return []

    red_list = sorted(red_balls[:max_pairs], key=bbox_area, reverse=True)
    green_list = sorted(green_balls[:max_pairs], key=bbox_area, reverse=True)

    pairs: List[Tuple[Ball, Ball]] = []
    used_green: set = set()

    for red in red_list:
        rx, ry = red[0], red[1]
        r_area = bbox_area(red)
        best_green = None
        best_dist = float("inf")
        best_green_idx = -1

        for gi, grn in enumerate(green_list):
            if gi in used_green:
                continue
            g_area = bbox_area(grn)
            if r_area > 0 and g_area > 0:
                ratio = min(r_area, g_area) / max(r_area, g_area)
                if ratio < min_area_ratio:
                    # Area terlalu timpang -> kemungkinan besar dari gate berbeda, abaikan.
                    continue
            gx, gy = grn[0], grn[1]
            dist = math.hypot(rx - gx, ry - gy)
            if dist < best_dist:
                best_dist = dist
                best_green = grn
                best_green_idx = gi

        if best_green is not None:
            used_green.add(best_green_idx)
            pairs.append((red, best_green))

        if len(pairs) >= max_pairs:
            break

    def _pair_avg_area(pair: Tuple[Ball, Ball]) -> float:
        r, g = pair
        return (bbox_area(r) + bbox_area(g)) / 2.0

    pairs.sort(key=_pair_avg_area, reverse=True)
    return pairs
