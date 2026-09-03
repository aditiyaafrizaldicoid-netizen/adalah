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

RED   = "red"
GREEN = "green"

LEFT  = "left"
RIGHT = "right"

# ── DUA LINTASAN ARENA ──────────────────────────────────────────────────────────
# Arena bisa dipasang dalam dua cerminan. Keduanya ditulis LENGKAP di sini, bukan
# satu tabel yang dibalik dengan kode: tabel yang dibalik secara terprogram tidak
# bisa dibaca sekilas untuk memastikan mana yang benar, dan inilah tabel yang
# menentukan ke arah mana kapal membanting saat cuma satu penanda terlihat.
#
# Sisi selalu dilihat DARI HALUAN kapal yang sedang maju menyusuri lintasan.
#
#   LINTASAN A : bola hijau KANAN, bola merah KIRI, box biru KIRI, box hijau KANAN
#   LINTASAN B : kebalikannya — dan inilah konfigurasi bawaan kapal saat ini
LINTASAN_A = "A"
LINTASAN_B = "B"

_TABEL_LINTASAN: Dict[str, Dict[str, str]] = {
    LINTASAN_A: {
        "green":     RIGHT,
        "red":       LEFT,
        "blue_box":  LEFT,
        "green_box": RIGHT,
    },
    LINTASAN_B: {
        "green":     LEFT,
        "red":       RIGHT,
        "blue_box":  RIGHT,
        "green_box": LEFT,
    },
}

# Lintasan yang berlaku sekarang. B adalah bawaan, sesuai konfigurasi kapal
# sebelum fitur pemilih lintasan ada — supaya kapal yang belum pernah menerima
# perintah apa pun berperilaku persis seperti sebelumnya.
_LINTASAN_AKTIF: str = LINTASAN_B

# Tabel gabungan yang benar-benar dibaca side_of(). Satu tabel supaya
# side_of()/channel_sign() melayani bola dan box tanpa pemanggil perlu tahu
# sedang berurusan dengan yang mana.
_MARKER_SIDE: Dict[str, str] = dict(_TABEL_LINTASAN[_LINTASAN_AKTIF])


def daftar_lintasan() -> tuple:
    """Nama lintasan yang dikenali, untuk validasi di sisi pemanggil."""
    return tuple(_TABEL_LINTASAN.keys())


def lintasan_aktif() -> str:
    """Lintasan yang SEDANG berlaku ("A" atau "B")."""
    return _LINTASAN_AKTIF


def snapshot() -> Dict[str, str]:
    """
    Seluruh tabel sisi yang berlaku, diambil dalam SATU pembacaan.

    KENAPA PERLU: tiap panggilan side_of() memang atomik, tapi HIMPUNAN beberapa
    panggilan tidak. Pemanggil yang menanyakan empat penanda satu per satu bisa
    terbelah oleh pergantian lintasan di tengahnya — misalnya bola merah sudah
    memakai tabel baru sementara bola hijau masih tabel lama, sehingga keduanya
    sesaat menunjuk sisi yang sama dan kemudi kehilangan arah untuk satu frame.
    Fungsi ini mengambil rujukan tabelnya sekali, jadi seluruh isinya dijamin
    berasal dari lintasan yang sama.

    Dalam praktik, celah itu paling lama satu frame dan hanya bisa terjadi saat
    operator menekan tombol — dan pergantian sudah ditolak selagi misi berjalan
    (lihat _terapkan_lintasan di connection/websocket.py), yaitu satu-satunya saat
    kemudi otonom benar-benar bergantung padanya. Fungsi ini disediakan untuk
    pemanggil yang tetap ingin kepastian penuh dalam satu frame.
    """
    return dict(_MARKER_SIDE)


def sisi_lintasan(nama: str) -> Dict[str, str]:
    """Salinan tabel sisi milik satu lintasan — untuk ditampilkan, bukan diubah."""
    return dict(_TABEL_LINTASAN[str(nama).strip().upper()])


def set_lintasan(nama: str) -> bool:
    """
    Ganti lintasan yang berlaku. True kalau berubah, False kalau nama tidak dikenal
    atau sudah sama.

    KENAPA TABELNYA DIGANTI UTUH, BUKAN DIUBAH ISINYA: modul ini dibaca thread
    kontrol/vision pada ~30 FPS sementara yang mengubahnya adalah thread WebSocket.
    Mengubah isi dict yang sedang dipakai membuat pembaca bisa menangkap keadaan
    setengah jadi — misalnya bola merah sudah pindah sisi sementara bola hijau
    belum, yang berarti KEDUA bola sesaat menunjuk sisi yang sama dan kemudi
    kehilangan arah. Mengikat ulang nama modul ke dict BARU bersifat atomik di
    bawah GIL: pembaca melihat tabel lama seutuhnya atau tabel baru seutuhnya.
    """
    global _LINTASAN_AKTIF, _MARKER_SIDE
    kunci = str(nama or "").strip().upper()
    if kunci not in _TABEL_LINTASAN:
        return False
    if kunci == _LINTASAN_AKTIF:
        return False
    _MARKER_SIDE = dict(_TABEL_LINTASAN[kunci])
    _LINTASAN_AKTIF = kunci
    return True


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
