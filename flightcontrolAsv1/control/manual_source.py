"""
Sumber kendali manual ASV: MINI PC (companion computer) atau REMOTE RC fisik.

Modul ini murni/stateless — hanya konstanta + normalisasi input. Status "siapa yang
sedang memegang kendali" disimpan di ASVController (core/client.py), yang juga
bertugas MEMBLOKIR perintah gerak dari mini PC saat kendali ada di remote.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KENAPA REMOTE FISIK TIDAK BISA MENGAMBIL ALIH SEBELUM ADA MODUL INI

Ada DUA sebab, dan keduanya harus diatasi bersama:

1. Nilai "lepas override" yang dikirim SALAH.
   Pada pesan MAVLink RC_CHANNELS_OVERRIDE, arti nilai tiap channel adalah:
       0      → LEPASKAN channel ini, kembalikan ke receiver RC (remote fisik)
       65535  → ABAIKAN field ini; override yang sedang berjalan TETAP DIPERTAHANKAN
       1000-2000 → nilai PWM override
   Kode lama mengirim 65535 ke semua channel untuk "melepas" kendali — yang artinya
   justru "jangan ubah apa-apa". Override lama tetap aktif dan remote tetap terkunci.

2. Mini PC terus-menerus mengirim override.
   main.py memanggil send_manual_rc_drive() setiap frame (~15x/detik), TERMASUK saat
   misi tidak berjalan (mengirim netral 0,0 supaya kapal diam). Selama itu terjadi,
   melepaskan override sekali pun percuma: frame berikutnya langsung merebut kembali
   kendali dari remote. Karena itu pelepasan HARUS disertai gerbang (gate) yang
   menghentikan semua pengiriman override dari mini PC — lihat
   ASVController.set_manual_source().

CATATAN JARING PENGAMAN: ArduPilot punya parameter RC_OVERRIDE_TIME (default 3 detik).
Kalau mini PC berhenti mengirim override — entah sengaja, hang, atau mati — ArduPilot
otomatis mengembalikan kendali ke receiver RC setelah selang waktu itu. Jadi kegagalan
total mini PC tetap berujung ke remote fisik, hanya lebih lambat beberapa detik
dibanding pelepasan eksplisit di sini.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from typing import Optional

# Nilai channel RC_CHANNELS_OVERRIDE (lihat penjelasan di atas — JANGAN ditukar).
RC_RELEASE = 0      # lepaskan channel ke receiver RC / remote fisik
RC_IGNORE = 65535   # jangan ubah channel ini (override lama tetap jalan)

MINIPC = "minipc"
REMOTE = "remote"
VALID = (MINIPC, REMOTE)

# Sinonim yang mungkin dikirim base station / operator, dipetakan ke nilai kanonik.
_ALIASES = {
    "minipc": MINIPC,
    "mini_pc": MINIPC,
    "mini-pc": MINIPC,
    "pc": MINIPC,
    "companion": MINIPC,
    "jetson": MINIPC,
    "auto": MINIPC,
    "remote": REMOTE,
    "rc": REMOTE,
    "radio": REMOTE,
    "transmitter": REMOTE,
    "tx": REMOTE,
}


def normalize(value) -> Optional[str]:
    """
    Ubah input bebas dari base station menjadi 'minipc'/'remote'.

    Mengembalikan None (BUKAN default diam-diam) kalau nilainya tidak dikenal —
    pemanggil wajib menolaknya secara eksplisit. Menebak default di sini berbahaya:
    salah tebak berarti kapal bergerak dikendalikan pihak yang tidak diinginkan
    operator, dan operator tidak akan tahu perintahnya tidak dipahami.
    """
    if value is None:
        return None
    key = str(value).strip().lower()
    return _ALIASES.get(key)


def label(source: str) -> str:
    """Nama yang enak dibaca manusia untuk log & OSD."""
    return "REMOTE RC fisik" if source == REMOTE else "MINI PC"
