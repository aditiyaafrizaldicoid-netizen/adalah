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

TIGA BENTUK YANG DITERIMA:
    2                                     nomor index — paling rapuh, bisa bertukar
    /dev/v4l/by-id/usb-046d_C270_..._0     path lengkap — paling tepat
    C270                                  POTONGAN NAMA — tahan penggantian kamera

    Potongan nama ada karena nama by-id memuat NOMOR SERI: mengganti kamera dengan
    unit lain bermodel sama sudah cukup membuat .env menunjuk perangkat yang tidak
    ada. Itu terjadi dua kali dalam sepekan pada kamera bawah air kapal ini.

    Potongan yang cocok dengan LEBIH DARI SATU perangkat ditolak, bukan ditebak —
    menebak berarti kamera permukaan dan bawah air bisa tertukar tanpa satu pun
    pesan, dan kapal akan mencari bola di pemandangan bawah air yang keruh.
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

    # Bukan angka, bukan path → perlakukan sebagai POTONGAN NAMA perangkat.
    #
    # KENAPA (dua kali dalam seminggu): nama by-id memuat nomor seri, jadi ia
    # berubah setiap kali kamera diganti — dan kamera bawah air ini sudah dua kali
    # diganti karena kemasukan air. Tiap penggantian membuat .env menunjuk
    # perangkat yang tidak ada, dan kegagalannya sunyi: foto tetap jadi, dari
    # kamera yang salah.
    #
    # Dengan potongan nama, ".env" cukup berisi "C270" dan tetap benar walau unit
    # fisiknya ditukar dengan C270 lain. Yang hilang cuma ketepatan membedakan DUA
    # kamera bermodel sama — dan kasus itu ditolak di bawah, bukan ditebak.
    cocok = [n for n in daftar_tersedia() if raw.lower() in n.lower()]

    # Hanya node penangkap gambar. Tiap kamera juga mendaftarkan index1 yang
    # bukan sumber frame, dan memilihnya menghasilkan kamera yang "terbuka" tapi
    # tidak pernah memberi gambar.
    tangkap = [n for n in cocok if n.endswith("-video-index0")] or cocok

    if len(tangkap) == 1:
        hasil = f"{DIR_BY_ID}/{tangkap[0]}"
        print(f"[Kamera] 🔎 {nama_env or 'Nilai'}='{raw}' dicocokkan ke {hasil}")
        return hasil

    if len(tangkap) > 1:
        # Menebak salah satu berarti kamera permukaan dan bawah air bisa tertukar
        # tanpa satu pun pesan — persis kegagalan yang modul ini ada untuk mencegah.
        print(f"[Kamera] ⛔ {nama_env or 'Nilai'}='{raw}' cocok dengan LEBIH DARI SATU "
              f"perangkat, jadi tidak bisa dipastikan yang mana:")
        for n in tangkap:
            print(f"[Kamera]      {DIR_BY_ID}/{n}")
        print("[Kamera]    Tulis nama lengkapnya di .env supaya tidak ambigu.")
        return default

    print(f"[Kamera] ⛔ {nama_env or 'Nilai'}='{raw}' bukan angka, bukan path "
          f"(/dev/...), dan tidak cocok dengan perangkat mana pun.")
    _sebutkan_yang_tersedia()
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
