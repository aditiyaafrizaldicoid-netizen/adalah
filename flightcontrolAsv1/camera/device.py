"""
Penunjuk perangkat kamera: nomor index ATAU path perangkat.

Dipakai bersama kamera permukaan (main.py) dan kamera bawah air
(camera/underwater.py) supaya keduanya menerima bentuk yang sama persis.

KENAPA PATH PERLU DIDUKUNG:
    Nomor /dev/videoN diberikan sesuai urutan enumerasi USB dan BISA BERTUKAR
    antar boot — apalagi setelah kamera kedua terpasang. Kalau tertukar, kamera
    bawah air menjadi kamera DETEKSI: kapal mencari bola di pemandangan bawah air
    yang keruh, dan foto box biru justru diambil dari permukaan. Keduanya salah,
    keduanya tanpa satu pun error.

    Path /dev/v4l/by-id/... terikat pada perangkat fisiknya, jadi tidak bisa
    tertukar. Dengan dua kamera terpasang, itulah cara yang aman.

    Lihat nama stabilnya dengan:  ls -l /dev/v4l/by-id/
"""
import os

# Tempat nama perangkat yang STABIL berada. Symlink di sini terikat pada perangkat
# fisiknya (vendor, produk, nomor seri), jadi tidak bertukar antar boot.
DIR_BY_ID = "/dev/v4l/by-id"


def daftar_tersedia():
    """Nama perangkat kamera yang BENAR-BENAR terpasang sekarang."""
    try:
        return sorted(os.listdir(DIR_BY_ID))
    except OSError:
        return []


def _sebutkan_yang_tersedia():
    """
    Cetak kamera yang sedang terpasang, di samping pesan "perangkat tidak ada".

    KENAPA: nama by-id memuat NOMOR SERI perangkat, jadi ia berubah setiap kali
    kameranya diganti — dan mengganti kamera adalah perawatan biasa, bukan kejadian
    langka. Kamera bawah air kebanjiran lalu ditukar dengan unit lain sudah cukup
    untuk membuat .env menunjuk perangkat yang tidak ada lagi.

    Kegagalannya kemudian SUNYI di tempat yang salah: fotonya tetap jadi, tetap
    ber-geo-tag, tetap terkirim ke dashboard — hanya diambil kamera permukaan.
    Yang dibutuhkan operator saat itu bukan "perangkat tidak ada", melainkan nama
    yang harus ditulis sebagai gantinya. Jadi jawabannya dicetak di sini, bukan
    ditinggalkan untuk dicari sendiri.
    """
    tersedia = daftar_tersedia()
    if not tersedia:
        print(f"[Kamera]    Tidak ada satu pun perangkat di {DIR_BY_ID} — "
              f"periksa kabel USB.")
        return
    print(f"[Kamera]    Yang TERPASANG sekarang ({DIR_BY_ID}):")
    for nama in tersedia:
        print(f"[Kamera]      {DIR_BY_ID}/{nama}")
    print("[Kamera]    Salin salah satu di atas ke .env, lalu jalankan ulang.")


def parse(raw, default=None, nama_env=""):
    """
    Terjemahkan isi .env jadi penunjuk perangkat yang bisa dipakai cv2.

    :return: int (index), str (path), atau `default` kalau kosong/tidak dikenal.
    """
    raw = str(raw or "").strip()
    if raw == "":
        return default

    if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
        return int(raw)

    if raw.startswith("/"):
        if not os.path.exists(raw):
            print(f"[Kamera] ⛔ Perangkat TIDAK ADA: '{raw}'"
                  f"{f' ({nama_env})' if nama_env else ''}.")
            _sebutkan_yang_tersedia()
        return raw

    print(f"[Kamera] ⚠️ {nama_env or 'Nilai'}='{raw}' bukan angka maupun path "
          f"perangkat (/dev/...). Dipakai default: {default}.")
    return default


def sama(a, b) -> bool:
    """
    True kalau dua penunjuk mengarah ke perangkat yang SAMA.

    Path di-resolve dulu: /dev/v4l/by-id/... adalah symlink ke /dev/videoN, jadi
    membandingkan teksnya saja akan melewatkan kasus dua nama untuk satu kamera.
    Angka dan path tidak dibandingkan silang — keduanya tidak bisa dipastikan
    tanpa membuka perangkatnya.
    """
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        try:
            return os.path.realpath(a) == os.path.realpath(b)
        except OSError:
            return a == b
    return False
