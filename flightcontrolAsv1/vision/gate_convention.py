"""
Konvensi sisi gerbang — SATU-SATUNYA sumber kebenaran tentang warna bola mana yang
menandai tepi KIRI dan tepi KANAN lintasan ASV.

KENAPA HARUS DIPUSATKAN DI SINI (bug nyata di lapangan):
    Setiap koreksi kemudi yang melibatkan SATU bola saja — titik tengah semu saat
    cuma satu warna terdeteksi, condong saat TRANSITIONING, guard keseimbangan celah
    gerbang — arahnya SEPENUHNYA ditentukan oleh pemetaan warna→sisi ini. Sebelum
    modul ini ada, pemetaan itu ditulis ulang sebagai literal "left"/"right" di
    banyak tempat terpisah (mission_engine.py di 6 titik, tracker.py di 2 titik,
    tools/buoy_sim.py di 1 titik), semuanya menganggap MERAH = KIRI & HIJAU = KANAN.

    Arena yang sesungguhnya memakai kebalikannya: MERAH = KANAN, HIJAU = KIRI.
    Akibatnya setiap koreksi "menjauh dari bola" justru mengarahkan kapal MENABRAK
    bola tersebut, dan guard keseimbangan celah mati total tanpa suara (lihat
    _compute_gate_clearance_steer: kedua celah jadi negatif → langsung return 0.0).

    Dengan modul ini, konvensi cukup dibalik di SATU tempat (BUOY_SIDE di bawah) dan
    seluruh logika ikut menyesuaikan — tidak ada lagi literal sisi yang tercecer dan
    bisa melenceng sendiri-sendiri.

Modul ini murni/stateless dan sengaja TIDAK berada di dalam paket `control` maupun
`vision` secara eksklusif secara logika — sama seperti ball_pairing.py, keduanya
boleh mengimpornya tanpa menimbulkan dependency silang.
"""

from typing import Dict

# ── Pemetaan warna bola → tepi lintasan yang ditandainya ────────────────────────
# UBAH DI SINI SAJA kalau arena memakai konvensi sebaliknya (mis. IALA region A/B
# yang berbeda, atau lomba dengan aturan lain). Tidak ada literal sisi lain di
# codebase yang perlu ikut diubah.
#
# Arena ASV yang dipakai saat ini: bola MERAH di sebelah KANAN lintasan, bola HIJAU
# di sebelah KIRI lintasan (dilihat dari haluan kapal yang sedang maju).
BUOY_SIDE: Dict[str, str] = {
    "red":   "right",
    "green": "left",
}

# Box misi mengikuti konvensi yang SAMA, dengan biru mengambil peran merah:
# box biru menandai tepi KANAN lintasan, box hijau menandai tepi KIRI.
#
# Ini yang membuat step BOX_CHANNEL bisa menyusuri celah walau kedua box TIDAK
# berdampingan seperti bola. Karena tiap box sendirian sudah cukup untuk menentukan
# di sisi mana lintasannya, kapal tidak perlu melihat keduanya sekaligus — dan
# memang jarang bisa, karena letaknya berselang di sepanjang lintasan.
BOX_SIDE: Dict[str, str] = {
    "blue_box":  "right",
    "green_box": "left",
}

# Satu tabel gabungan supaya side_of()/channel_sign() melayani bola dan box tanpa
# pemanggil perlu tahu sedang berurusan dengan yang mana.
_MARKER_SIDE: Dict[str, str] = {**BUOY_SIDE, **BOX_SIDE}

RED   = "red"
GREEN = "green"

LEFT  = "left"
RIGHT = "right"


def side_of(color: str) -> str:
    """
    Tepi lintasan ("left"/"right") yang ditandai penanda `color` — bola gerbang
    maupun box misi.

    Melempar KeyError untuk warna yang tidak dikenal — DISENGAJA. Warna bola hanya
    berasal dari class YOLO 0/1 yang sudah dipetakan di tracker.py; warna asing di
    sini berarti ada bug pemanggilan, dan menutupinya dengan default "left"/"right"
    akan menghasilkan kemudi yang diam-diam salah arah (persis kelas bug yang
    modul ini ada untuk mencegahnya).
    """
    return _MARKER_SIDE[color]


def channel_sign(color: str) -> float:
    """
    Arah lintasan (jalur yang harus dilewati kapal) relatif terhadap bola warna ini,
    dalam sumbu X citra kamera:

        +1.0 → lintasan ada di SEBELAH KANAN bola (bola ini penanda tepi KIRI)
        -1.0 → lintasan ada di SEBELAH KIRI  bola (bola ini penanda tepi KANAN)

    Inilah nilai yang membuat penentuan titik tengah saat hanya satu bola terlihat
    bergantung MURNI pada identitas warna bola — bukan pada posisi bola relatif
    terhadap garis tengah frame. Bola yang bergerak menyeberangi tengah frame TIDAK
    lagi membalik/melonjakkan arah koreksi.
    """
    return 1.0 if side_of(color) == LEFT else -1.0


def steer_sign_toward(side: str) -> float:
    """Tanda steer untuk membelok KE ARAH sisi tertentu: kiri = -1.0, kanan = +1.0."""
    return -1.0 if side == LEFT else 1.0


def virtual_gate_center_x(ball_x: float, color: str, half_gate_px: float) -> float:
    """
    Perkiraan titik tengah gerbang saat HANYA satu bola yang terlihat.

    Bola pasangannya (di seberang lintasan) diasumsikan berada `2 * half_gate_px`
    dari bola ini ke arah lintasan, sehingga titik tengahnya:

        center_x = ball_x + channel_sign(warna) * half_gate_px

    Sifat penting fungsi ini (inti perbaikan bug titik tengah satu-bola):
      - KONTINU & MONOTON terhadap ball_x — tidak ada abs(), tidak ada percabangan
        "bola di paruh kiri/kanan frame", jadi tidak ada loncatan nilai saat bola
        menyeberangi garis tengah frame.
      - TIDAK di-clamp ke [0, lebar_frame]. Titik tengah gerbang memang BOLEH berada
        di luar frame ketika bola pasangannya sudah keluar frame — meng-clamp-nya ke
        tepi citra justru membuat error piksel MENTOK di setengah lebar frame
        (kemudi banting penuh) padahal gerbangnya cuma sedikit di luar pandangan.
        Pemanggil yang perlu menggambar titik ini yang bertanggung jawab men-clamp
        koordinat GAMBARnya sendiri.
    """
    return float(ball_x) + channel_sign(color) * float(half_gate_px)
