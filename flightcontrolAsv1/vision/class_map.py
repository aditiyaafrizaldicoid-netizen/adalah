"""
Peta kelas model YOLO → PERAN dalam misi.

SATU-SATUNYA tempat kode ini menerjemahkan keluaran model menjadi "ini bola hijau",
"ini box biru", dan seterusnya.

KENAPA HARUS BERBASIS NAMA, BUKAN INDEKS (bug nyata, ditemukan saat model diperbarui):
    Sebelum modul ini ada, tracker.py memutuskan warna dengan `if cls == 0: hijau
    else: merah`, dan main.py menyaring dengan `target_class=[0, 1]`. Keduanya
    mengasumsikan urutan kelas model lama:

        best1.pt / best2.pt : {0: B_GREEN, 1: B_RED}

    Model baru menambahkan dua kelas box DAN MENOMORI ULANG semuanya:

        best.pt             : {0: BOX_biru, 1: BOX_ijo, 2: B_GREEN, 3: B_RED}

    Akibatnya, begitu best.pt dipasang: `target_class=[0, 1]` tidak lagi memilih
    bola sama sekali melainkan KEDUA BOX, lalu `cls == 0` membuat BOX_biru dibaca
    sebagai bola HIJAU dan BOX_ijo sebagai bola MERAH. Kapal akan mengemudi menuju
    "gerbang" yang tersusun dari dua box, dan bola asli tidak pernah terlihat.
    Tidak ada error, tidak ada log — cuma kapal yang berlayar ke arah yang salah.

    Indeks kelas adalah detail dataset: ia berubah setiap kali kelas ditambah,
    dihapus, atau diurutkan ulang saat melatih. Nama kelas adalah kontraknya. Modul
    ini menerjemahkan sekali di satu tempat, dan menolak dengan berisik kalau ada
    nama yang tidak dikenali — supaya kegagalannya terlihat saat boot, bukan di air.

CARA MENAMBAH KELAS BARU:
    Tambahkan namanya (huruf kecil) ke _NAME_TO_ROLE di bawah. Tidak ada tempat lain
    yang perlu diubah — tracker.py membangun petanya sendiri dari model.names.
"""

from typing import Dict

# ── Peran yang dikenali sistem ───────────────────────────────────────────────
# Bola gerbang: dipakai Gate State Machine di control/mission_engine.py. Sisi
# lintasan yang ditandai tiap warna TIDAK ditentukan di sini melainkan di
# vision/gate_convention.py — modul ini hanya soal "objek apa ini".
ROLE_GREEN_BUOY = "green"
ROLE_RED_BUOY = "red"

# Bola BIRU — kelas baru di model per 3 September 2026. Perannya di arena BELUM
# ditentukan, jadi sengaja TIDAK ikut membentuk gerbang dan TIDAK punya sisi di
# vision/gate_convention.py. Ia dideteksi, digambar, dan diteruskan ke mission
# engine, lalu berhenti di situ sampai ada step yang benar-benar memakainya.
#
# Kenapa dipisah setegas ini: bola biru muncul di air yang sama dengan bola gerbang.
# Kalau ia ikut terhitung sebagai penanda gerbang — atau bahkan cuma ikut menyumbang
# titik tengah fallback — kemudi kapal akan tertarik ke arahnya di sepanjang lintasan
# buoy, tanpa satu pun pesan error. Itu persis kelas bug yang modul ini ada untuk
# mencegah, cuma lewat pintu yang berbeda.
ROLE_BLUE_BUOY = "blue"

# Box misi foto: target step PHOTO_BOX. Box biru secara konsep adalah target bawah
# air dan box hijau target atas air, TAPI di arena box biru masih menyembul di atas
# permukaan — jadi keduanya dideteksi dari kamera permukaan yang sama. Tidak ada
# kamera underwater di sistem ini.
ROLE_BLUE_BOX = "blue_box"
ROLE_GREEN_BOX = "green_box"

# Bola yang MEMBENTUK GERBANG. Hanya dua warna ini yang boleh menggerakkan kemudi
# lewat Gate State Machine, titik tengah semu satu-bola, dan titik tengah fallback.
# Bola biru TIDAK di sini, dan itu disengaja — lihat catatan di ROLE_BLUE_BUOY.
GATE_BUOY_ROLES = (ROLE_GREEN_BUOY, ROLE_RED_BUOY)

# Semua bola, termasuk yang belum punya peran navigasi. Dipakai untuk hal-hal yang
# memang berlaku ke semua bola: pengumpulan deteksi dan penggambaran OSD.
BUOY_ROLES = GATE_BUOY_ROLES + (ROLE_BLUE_BUOY,)

BOX_ROLES = (ROLE_BLUE_BOX, ROLE_GREEN_BOX)
ALL_ROLES = BUOY_ROLES + BOX_ROLES

# Label yang enak dibaca manusia — dipakai di log dan nama berkas foto.
ROLE_LABELS: Dict[str, str] = {
    ROLE_GREEN_BUOY: "bola hijau",
    ROLE_RED_BUOY: "bola merah",
    ROLE_BLUE_BUOY: "bola biru",
    ROLE_BLUE_BOX: "box biru",
    ROLE_GREEN_BOX: "box hijau",
}

# ── Nama kelas di model (huruf kecil) → peran ────────────────────────────────
# Beberapa alias sengaja didaftarkan untuk satu peran yang sama: nama kelas ikut
# ejaan orang yang melabeli dataset, dan itu berubah antar sesi pelatihan. Mendaftar
# ejaan yang wajar di sini jauh lebih murah daripada kapal yang diam-diam buta
# terhadap satu kelas gara-gara "BOX_ijo" berubah jadi "box_green".
_NAME_TO_ROLE: Dict[str, str] = {
    # bola gerbang
    "b_green": ROLE_GREEN_BUOY,
    "green": ROLE_GREEN_BUOY,
    "green_ball": ROLE_GREEN_BUOY,
    "bola_hijau": ROLE_GREEN_BUOY,
    "b_red": ROLE_RED_BUOY,
    "red": ROLE_RED_BUOY,
    "red_ball": ROLE_RED_BUOY,
    "bola_merah": ROLE_RED_BUOY,
    "b_blue": ROLE_BLUE_BUOY,
    "blue": ROLE_BLUE_BUOY,
    "blue_ball": ROLE_BLUE_BUOY,
    "bola_biru": ROLE_BLUE_BUOY,
    # box misi foto
    "box_biru": ROLE_BLUE_BOX,
    "box_blue": ROLE_BLUE_BOX,
    "blue_box": ROLE_BLUE_BOX,
    "box_ijo": ROLE_GREEN_BOX,
    "box_hijau": ROLE_GREEN_BOX,
    "box_green": ROLE_GREEN_BOX,
    "green_box": ROLE_GREEN_BOX,
}


def role_of(class_name: str):
    """Peran untuk satu nama kelas, atau None kalau tidak dikenali."""
    return _NAME_TO_ROLE.get(str(class_name).strip().lower())


def build_role_map(model_names) -> Dict[int, str]:
    """
    Bangun peta {class_id: peran} dari `model.names` milik YOLO.

    Kelas yang namanya tidak ada di _NAME_TO_ROLE DIBUANG (tidak ikut dideteksi) dan
    dilaporkan ke stdout. Membuangnya diam-diam akan mengulang persis bug yang modul
    ini ada untuk mencegah; membuangnya dengan berisik membuat model yang salah
    pasang ketahuan di baris log pertama saat boot.

    :param model_names: dict {id: nama} atau list nama, sesuai YOLO.
    :return: {class_id: peran} — hanya kelas yang dikenali.
    """
    if isinstance(model_names, dict):
        pasangan = list(model_names.items())
    else:
        pasangan = list(enumerate(model_names or []))

    peta: Dict[int, str] = {}
    tidak_dikenal = []
    for cls_id, nama in pasangan:
        peran = role_of(nama)
        if peran is None:
            tidak_dikenal.append(f"{cls_id}:{nama}")
        else:
            peta[int(cls_id)] = peran

    if tidak_dikenal:
        print(f"[ClassMap] ⚠️ Kelas model tidak dikenali dan DIABAIKAN: "
              f"{', '.join(tidak_dikenal)}. Tambahkan namanya ke "
              f"vision/class_map.py kalau kelas ini seharusnya dipakai.")

    hilang = [r for r in ALL_ROLES if r not in peta.values()]
    if hilang:
        label = ", ".join(ROLE_LABELS[r] for r in hilang)
        print(f"[ClassMap] ℹ️ Model ini tidak punya kelas untuk: {label}. "
              f"Step misi yang membutuhkannya tidak akan pernah mendeteksi apa pun.")

    return peta
