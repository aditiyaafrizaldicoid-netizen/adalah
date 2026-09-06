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
            print(f"[Kamera] ⚠️ Perangkat '{raw}' tidak ada saat boot"
                  f"{f' ({nama_env})' if nama_env else ''} — tetap dicoba dibuka.")
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
