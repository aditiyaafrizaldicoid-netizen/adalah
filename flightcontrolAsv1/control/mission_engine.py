"""
MissionEngine - Autonomous Mission Sequence Executor untuk ASV.

Engine ini mengeksekusi mission steps secara berurutan:
- TRACKING_BUOY  : AI Vision PID untuk melewati gerbang bola hijau+merah
- SEQUENTIAL_BUOY: Lewati N pasang buoy (hijau+merah) berurutan tanpa perlu di-configure jumlahnya
- BUOY_CHASE     : Versi sederhana SEQUENTIAL_BUOY (cuma throttle + ignore_area_px2), selesai saat buoy habis dari frame
- GYRO_FORWARD   : Maju lurus dgn koreksi yaw kompas/gyro (heading-hold), berhenti di waktu ATAU saat buoy terdeteksi
- GOTO_GPS       : Navigasi ke koordinat GPS tertentu
- TAKE_IMAGE     : Berhenti dan ambil foto/rekam video
- HOLD           : Berhenti di posisi saat ini
- FINISH         : Selesaikan misi dan tahan posisi

Format Mission Steps (JSON array):
[
    { "id": 1, "type": "TRACKING_BUOY", "name": "Gate 1-10",  "pass_count": 5, "throttle": 0.4 },
    { "id": 2, "type": "GOTO_GPS",      "name": "Waypoint A", "lat": -7.921, "lon": 112.597 },
    { "id": 3, "type": "TAKE_IMAGE",    "name": "Foto Spot",  "duration_sec": 3.0 },
    { "id": 4, "type": "FINISH",        "name": "Mission End" }
]

Field `throttle` (0.0-1.0) pada TRACKING_BUOY & SEQUENTIAL_BUOY bersifat OPSIONAL —
jika tidak diisi, engine fallback ke speed_scheduler.max_base_throttle (global,
live-tunable via WS PID config). Lihat _resolve_step_throttle().

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gate Locking & Transition Maneuver — State Machine

SEARCHING → LOCKED → TRANSITIONING → CLEARED → buoy_pass_count += 1 → SEARCHING

  SEARCHING    : Belum ada pasangan bola terlihat. Gunakan fallback gate_x dari tracker.
  LOCKED       : Kedua bola (merah+hijau) terlihat bersamaan. Kunci pasangan ini, PID ke midpoint.
  TRANSITIONING: Satu bola hilang saat LOCKED. Manuver condong ke arah bola yang hilang.
                 DILARANG memasangkan bola tersisa dengan bola dari gerbang berikutnya.
  CLEARED      : Bola tersisa juga hilang. Gate dinyatakan terlewati. Reset ke SEARCHING.

Aturan lean saat TRANSITIONING:
  - Bola yang hilang duluan menentukan arah condong: kapal DIPAKSA condong KE ARAH
    SISI bola tersebut (steer konstan). Sisi setiap warna TIDAK boleh ditulis sebagai
    literal di file ini — diambil dari vision/gate_convention.py. Pada arena saat ini
    (merah = KANAN, hijau = KIRI): merah hilang duluan → condong KANAN, hijau hilang
    duluan → condong KIRI.
  - Steer KONSTAN (TRANSITION_LEAN_MAGNITUDE), BUKAN proporsional terhadap posisi bola
    tersisa di layar — kapal harus menahan arah itu sampai bola tersisa JUGA hilang,
    apa pun posisi bola tersisa saat itu. Steer proporsional/adaptif di sini pernah
    dicoba tapi terbukti membuat kapal goyah (nyaris lurus saat bola tersisa kebetulan
    dekat tengah frame) sehingga berisiko menabrak.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os
import time
import math
import threading
from typing import Optional, List, Dict, Any, Tuple


from camera.geotag import save_geotagged_image
from control.speed_scheduler import SpeedScheduler
from vision.ball_pairing import sort_ball_pairs
from vision.class_map import ROLE_BLUE_BOX, ROLE_GREEN_BOX, ROLE_LABELS
from vision.gate_convention import (
    LEFT,
    virtual_gate_center_x,
    channel_sign,
    side_of,
    steer_sign_toward,
)


class MissionEngine:
    """
    Finite State Machine untuk mengeksekusi mission steps otonom.

    Menggunakan Steering Normalized & SpeedScheduler Throttle Ratio
    untuk kendali AI pada mode MANUAL via RC Override.
    """

    STATUS_IDLE       = "IDLE"
    STATUS_RUNNING    = "RUNNING"
    STATUS_PAUSED     = "PAUSED"
    STATUS_FINISHED   = "FINISHED"
    STATUS_ABORTED    = "ABORTED"

    STEP_TYPE_TRACKING_BUOY  = "TRACKING_BUOY"
    STEP_TYPE_GOTO_GPS       = "GOTO_GPS"
    STEP_TYPE_TAKE_IMAGE     = "TAKE_IMAGE"
    STEP_TYPE_HOLD           = "HOLD"
    STEP_TYPE_FINISH         = "FINISH"
    STEP_TYPE_START          = "START"
    STEP_TYPE_CUSTOM_FORWARD = "CUSTOM_FORWARD"  # Maju lurus/serong dengan heading offset konstan
    STEP_TYPE_PRECISION_TURN = "PRECISION_TURN"  # Belok presisi ke sudut target
    STEP_TYPE_TIMED_STEER    = "TIMED_STEER"     # Manuver timer RC override (MANUAL mode)
    STEP_TYPE_STEER_UNTIL_GATE = "STEER_UNTIL_GATE"  # TIMED_STEER yang berhenti saat GERBANG (merah+hijau) terlihat
    STEP_TYPE_SEQUENTIAL_BUOY = "SEQUENTIAL_BUOY"  # Lewati N pasang buoy (hijau+merah) secara berurutan
    STEP_TYPE_GYRO_FORWARD   = "GYRO_FORWARD"    # Maju lurus dgn koreksi yaw kompas/gyro, berhenti di waktu ATAU saat buoy terdeteksi
    STEP_TYPE_BUOY_CHASE     = "BUOY_CHASE"      # Versi sederhana SEQUENTIAL_BUOY: cuma throttle + filter jarak (px²), selesai saat buoy habis dari frame
    STEP_TYPE_PHOTO_BOX      = "PHOTO_BOX"       # Cari, dekati, dan foto box biru & hijau — WAJIB setelah step buoy selesai
    STEP_TYPE_BOX_CHANNEL    = "BOX_CHANNEL"     # Susuri celah di antara box biru & hijau, berhenti & foto tiap box
    STEP_TYPE_STEER_UNTIL_BOX = "STEER_UNTIL_BOX"  # TIMED_STEER yang berhenti saat BOX (biru/hijau) terlihat
    STEP_TYPE_BOX_APPROACH   = "BOX_APPROACH"    # Cari box → dekati → menghindar. Tanpa foto, semua parameternya bisa di-tuning
    STEP_TYPE_DOCKING        = "DOCKING"         # Docking: tabrak 2 dari 3 bola biru yang berjajar

    # Step yang dianggap "misi tracking buoy". Menyelesaikan salah satunya membuka
    # kunci PHOTO_BOX (lihat tracking_buoy_completed & _advance_step).
    BUOY_STEP_TYPES = frozenset({
        STEP_TYPE_TRACKING_BUOY,
        STEP_TYPE_SEQUENTIAL_BUOY,
        STEP_TYPE_BUOY_CHASE,
    })

    # ── Resolusi Referensi ───────────────────────────────────────────────────
    # SEMUA konstanta berbasis piksel di bawah (GATE_IDENTITY_MAX_DIST_PX,
    # SEQ_MIN_PAIR_AREA_PX2, SEQ_IGNORE_AREA_PX2, dkk.) dikalibrasi & didokumentasikan
    # untuk resolusi kamera INI (1920x1080, Logitech MX Brio) — nilainya tetap
    # merepresentasikan hasil kalibrasi lapangan yang sebenarnya PADA resolusi ini.
    #
    # Kalau kamera dijalankan pada resolusi LAIN (mis. 640x360), __init__() memanggil
    # _apply_resolution_scaling() yang menskalakan ulang SEMUA konstanta ini secara
    # OTOMATIS berdasarkan rasio terhadap resolusi referensi ini — TIDAK perlu edit
    # kode manual setiap kali resolusi kamera diganti. Ini menggantikan proses rescale
    # manual per-konstanta yang sebelumnya dilakukan langsung di kode (rawan lupa/
    # keliru — pernah dua kali menyebabkan bug nyata dalam pengembangan proyek ini).
    REFERENCE_FRAME_WIDTH = 1920
    REFERENCE_FRAME_HEIGHT = 1080

    # Radius acceptance untuk GOTO_GPS: dianggap tiba jika < X meter dari target
    ARRIVAL_RADIUS_M = 2.0

    # Threshold heading error untuk PRECISION_TURN: dianggap selesai jika |error| <= X derajat
    TURN_ARRIVAL_THRESHOLD_DEG = 3.0

    # ---- Fase step BOX_CHANNEL ----
    # TRANSIT : menyusuri celah. Arah diambil dari penanda TERDEKAT lewat konvensi
    #           sisi (vision/gate_convention.py), jadi satu box terlihat sudah cukup.
    # AIM     : box target sudah cukup dekat. Laju dikurangi, kapal diputar agar box
    #           berada di tengah frame.
    # SETTLE  : sudah di tengah. Berhenti dan tunggu kapal diam supaya foto tidak buram.
    # SHOOT   : shutter diminta, menunggu frame kamera BERSIH dari main.py.
    BOX_TRANSIT = "TRANSIT"
    BOX_AIM     = "AIM"
    BOX_SETTLE  = "SETTLE"
    BOX_SHOOT   = "SHOOT"
    # Hanya dipakai mode "moving": setelah menjepret sambil jalan, kapal sedang
    # mengarah TEPAT ke box yang baru difoto dan harus membanting menjauh.
    BOX_EVADE   = "EVADE"

    # ---- Fase step BOX_APPROACH ----
    # SCAN     : box target belum terlihat. Kapal maju sambil menyapu ke satu arah.
    # APPROACH : box terlihat. Kapal memusatkannya sambil mendekat.
    # EVADE    : box sudah di tengah DAN sudah cukup dekat. Membanting ke arah yang
    #            diminta selama sekian detik, lalu step selesai.
    # ---- Fase step DOCKING ----
    # SEARCH  : bola biru belum cukup terlihat. Kapal menyapu mencari area docking.
    # ACQUIRE : ketiga bola terlihat. Sisi sasaran DIPILIH dan DIKUNCI di sini.
    # ALIGN   : mengemudi ke titik tengah pasangan yang sudah dikunci.
    # RAM     : sasaran terlalu dekat / sudah di bawah haluan. Maju menabrak.
    DOCK_SEARCH  = "SEARCH"
    DOCK_ACQUIRE = "ACQUIRE"
    DOCK_ALIGN   = "ALIGN"
    DOCK_RAM     = "RAM"

    BAP_SCAN     = "SCAN"
    BAP_APPROACH = "APPROACH"
    # Hanya dilewati kalau step diminta memotret (field `photo`). Default step ini
    # TIDAK memotret sama sekali — lihat BAP_PHOTO_MODE.
    BAP_SHOOT    = "SHOOT"
    BAP_EVADE    = "EVADE"

    # ---- Fase step PHOTO_BOX ----
    # SEARCH   : box target belum terlihat. Maju pelan sambil menyapu.
    # ALIGN    : box terlihat tapi belum lurus di depan haluan. Putar untuk memusatkan.
    # APPROACH : sudah lurus, belum cukup dekat. Maju sambil terus menjaga pusat.
    # SETTLE   : cukup dekat. Berhenti dan tunggu kapal diam supaya foto tidak buram.
    # SHOOT    : shutter diminta, menunggu frame kamera BERSIH dari main.py.
    PHOTO_SEARCH   = "SEARCH"
    PHOTO_ALIGN    = "ALIGN"
    PHOTO_APPROACH = "APPROACH"
    PHOTO_SETTLE   = "SETTLE"
    PHOTO_SHOOT    = "SHOOT"

    # ---- Gate State Machine states ----
    GATE_SEARCHING    = "SEARCHING"
    GATE_LOCKED       = "LOCKED"
    GATE_TRANSITIONING = "TRANSITIONING"
    GATE_CLEARED      = "CLEARED"

    # Steer PAKSA/KONSTAN (-1..+1) saat TRANSITIONING (satu bola hilang duluan).
    # SENGAJA konstan, BUKAN proporsional terhadap posisi bola tersisa — kapal harus
    # betul-betul DIPAKSA menuju sisi gerbang yang terbuka dan MENAHAN arah itu sampai
    # bola tersisa juga hilang, terlepas dari di mana posisi bola tersisa di layar.
    # Steer proporsional/adaptif di sini terbukti membuat kapal "goyah" (nyaris lurus
    # saat bola tersisa kebetulan dekat tengah frame) sehingga kapal kehilangan arah
    # dan berisiko menabrak salah satu bola.
    TRANSITION_LEAN_MAGNITUDE = 0.4

    # Jarak maksimum (piksel) untuk mengenali bola yang sama saat LOCKED/TRANSITIONING.
    # Bola yang lebih jauh dari ini dianggap bola dari gerbang lain dan diabaikan.
    # 900px (~47% frame 1920px, kamera Logitech MX Brio) — diskalakan 3x dari nilai
    # asli 300px @ 640px agar makna relatifnya (persentase lebar frame) tetap sama.
    GATE_IDENTITY_MAX_DIST_PX = 900

    # Timeout (detik) maksimum di state LOCKED sebelum di-reset ke SEARCHING.
    # Handle kasus kapal berhenti menghadap gate tapi tidak maju / bola tidak hilang-hilang.
    GATE_LOCKED_TIMEOUT_SEC = 8.0

    # Rasio pertumbuhan area (dari area pasangan SAAT PERTAMA LOCK) yang dianggap
    # bukti kapal SUDAH MENDEKAT/MELEWATI gerbang — dipakai HANYA saat
    # GATE_LOCKED_TIMEOUT_SEC terlampaui TAPI kedua bola masih terlihat terus-menerus
    # (kasus di mana kamera/FOV tidak membuat bola keluar frame saat kapal benar-benar
    # lewat — mis. gerbang sempit atau kamera bersudut lebar — sehingga gate TIDAK
    # PERNAH mencapai CLEARED via jalur normal "kedua bola hilang", padahal kapal
    # sudah nyata-nyata lewat).
    #
    # Kalau area pasangan sudah membesar >= rasio ini sejak saat lock pertama kali,
    # itu bukti kapal BENAR mendekat (ukuran bola membesar karena jarak mengecil),
    # bukan cuma diam menghadap gerbang dari jauh (area tidak membesar berarti jarak
    # tidak berubah) — dihitung sebagai 1 pass VALID (panggil _handle_gate_cleared)
    # alih-alih di-reset diam-diam ke SEARCHING tanpa hitungan sama sekali seperti
    # sebelumnya. Kalau area TIDAK membesar cukup, perilaku lama (reset tanpa hitung)
    # tetap dipertahankan sebagai jaring pengaman terhadap false-count.
    #
    # 1.5 = area minimal 1.5x lebih besar dari saat lock. BELUM diverifikasi di
    # lapangan — turunkan kalau pass valid masih sering tidak terhitung, naikkan
    # kalau mulai ada false-count (gate dihitung padahal kapal cuma diam/mundur).
    GATE_LOCKED_TIMEOUT_AREA_GROWTH_MIN_RATIO = 1.5

    # Timeout (detik) maksimum di state TRANSITIONING sebelum dipaksa CLEARED.
    # Handle kasus bola tersisa terus terlihat (kapal tidak maju / false detection).
    GATE_TRANSITIONING_TIMEOUT_SEC = 4.0

    # ── Sequential Buoy specific thresholds ────────────────────────────────
    # Timeout (detik) maksimum di state SEARCHING pada SEQUENTIAL_BUOY sebelum
    # dipaksa advance step. Handle kasus:
    #   - Pasangan terakhir hanya 1 bola terlihat (tidak ada pasangan valid)
    #   - Semua pasangan sudah terlewati tapi ada bola jauh yang masih terdeteksi
    # Catatan: timer baru mulai berjalan SETELAH pasangan pertama dikunci (cleared > 0),
    # sehingga tidak memotong waktu approach ke pasangan pertama.
    SEQ_SEARCHING_TIMEOUT_SEC = 12.0

    # Area rata-rata minimum (piksel²) untuk bola agar dianggap valid sebagai target LOCK.
    # Pasangan buoy dengan area rata-rata < nilai ini dianggap terlalu jauh dan dilewati.
    # Kapal tidak mengunci pasangan tersebut dan tetap maju menunggu bola yang lebih dekat.
    # 27000px² @ 1920x1080 (kamera Logitech MX Brio) — diskalakan dari nilai asli
    # 4000px² @ 640x480 dengan faktor luas (3× lebar × 2.25× tinggi = 6.75×), BUKAN
    # sekadar 3× linear, karena ini ukuran AREA bukan jarak. Nilai asli 4000 sendiri
    # sudah dinaikkan dari 1600 setelah dikonfirmasi langsung di lapangan (arena danau
    # terbuka) bahwa 1600 masih terlalu longgar — kapal masih menganggap cluster buoy
    # yang JAUH (di seberang danau) sebagai target valid. Perlu verifikasi ulang di
    # lapangan pada resolusi baru ini; turunkan lagi jika bola dekat jadi sering
    # terlewat, naikkan jika kapal masih tertarik ke bola jauh.
    SEQ_MIN_PAIR_AREA_PX2 = 27000

    # Area rata-rata minimum (piksel²) untuk pasangan bola agar DIANGGAP SEBAGAI
    # KANDIDAT SAMA SEKALI — beda dari SEQ_MIN_PAIR_AREA_PX2 di atas yang cuma
    # menentukan boleh-tidaknya sebuah pasangan di-LOCK. Pasangan yang area
    # rata-ratanya di bawah nilai ini dibuang SEBELUM sempat dipakai sebagai target
    # LOCK maupun target APPROACH (steer menuju midpoint-nya) — diperlakukan
    # sama seperti "tidak ada pasangan valid terdeteksi sama sekali".
    #
    # Kenapa perlu, terpisah dari SEQ_MIN_PAIR_AREA_PX2: sebelum ada floor ini,
    # SEARCHING akan mengejar (approach) pasangan SEKECIL/SEJAUH apa pun tanpa
    # batas bawah — kalau yang terdeteksi cuma objek jauh yang tidak akan pernah
    # cukup besar untuk di-LOCK (mis. buoy course lain di seberang danau, gerbang
    # finish yang jauh, atau noise/refleksi air yang kebetulan lolos filter rasio-
    # area & lebar-maksimum di sort_ball_pairs()), kapal akan terus mengejarnya
    # tanpa henti dan step SEQUENTIAL_BUOY tidak pernah bisa menyimpulkan "buoy
    # sudah habis" — SEQ_SEARCHING_TIMEOUT_SEC (12s) HANYA aktif setelah minimal
    # 1 pasangan sudah di-cleared, jadi sebelum pasangan PERTAMA berhasil dikunci,
    # tidak ada mekanisme timeout apa pun yang menghentikan pengejaran ini.
    #
    # 4000px² @ 1920x1080 (~15% dari SEQ_MIN_PAIR_AREA_PX2) — BELUM diverifikasi
    # di lapangan; naikkan kalau kapal masih tertarik ke buoy yang sangat jauh,
    # turunkan kalau buoy dekat yang sah malah ikut terbuang.
    SEQ_IGNORE_AREA_PX2 = 4000

    # ── Navigasi Satu-Bola (Sequential Buoy) ────────────────────────────────
    # Saat hanya SATU bola yang bisa dijadikan acuan — entah karena cuma satu warna
    # yang terdeteksi, atau pasangan gagal terbentuk sama sekali — arah koreksi
    # ditentukan MURNI oleh IDENTITAS WARNA bola lewat vision/gate_convention.py:
    # bola menandai salah satu TEPI lintasan, jadi jalur yang aman selalu berada di
    # sisi seberang bola itu, berapa pun posisi bola di layar.
    #
    # BUG YANG DIPERBAIKI (dilaporkan dari lapangan, dua gejala kembar):
    #   Versi lama memakai JARAK MUTLAK bola ke tengah frame — abs(ball_x - center_x)
    #   — sebagai ukuran bahaya, tanpa melihat bola ada di SISI MANA. Akibatnya:
    #     1. Besar koreksi memuncak tepat saat bola MENYEBERANGI garis tengah frame,
    #        lalu mengecil lagi setelah lewat — nilai titik tengah "melonjak" persis
    #        di perbatasan, padahal secara fisik tidak ada yang berubah mendadak.
    #     2. Arah koreksi TIDAK PERNAH ikut membalik saat bola menyeberang, sehingga
    #        kapal justru dikemudikan ke sisi yang salah (bola hijau yang menyeberang
    #        ke paruh KANAN frame malah melempar target ke KIRI secara ekstrem, dan
    #        sebaliknya untuk bola merah).
    #   Perbaikannya: pakai posisi BERTANDA relatif terhadap garis aman bola itu
    #   (lihat _compute_single_ball_avoid_steer di file ini, dan
    #   gate_convention.virtual_gate_center_x untuk fallback visual gate_x di
    #   vision/tracker.py) — kontinu dan monoton, tanpa percabangan
    #   paruh-kiri/paruh-kanan sama sekali.

    # Jarak lateral (piksel) yang harus dijaga antara bola tunggal dan haluan kapal.
    # Dipakai untuk DUA hal yang saling konsisten: (a) garis aman bola tunggal, dan
    # (b) perkiraan SETENGAH lebar gerbang saat memproyeksikan titik tengah semu dari
    # satu bola. 384px @ 1920px (~20% lebar frame) — BELUM diverifikasi di lapangan
    # sebagai jarak clearance yang optimal.
    SEQ_SINGLE_BALL_CLEARANCE_PX = 384

    # Steer maksimum (0..1) untuk koreksi menjaga-jarak dari bola tunggal, dicapai
    # saat bola tepat di tengah frame (urgency=1.0). Disamakan dengan
    # TRANSITION_LEAN_MAGNITUDE agar skalanya konsisten dengan manuver
    # condong/menghindar lain di file ini.
    SEQ_SINGLE_BALL_MAX_STEER = TRANSITION_LEAN_MAGNITUDE

    # ── Gate Balance Guard (saat LOCKED) ────────────────────────────────────
    # Toleransi KETIDAKSEIMBANGAN celah kiri-vs-kanan haluan (rasio 0..1, TANPA
    # satuan piksel — lihat _compute_gate_clearance_steer). Selama ketidakseimbangan
    # masih di bawah nilai ini, guard diam dan tracking midpoint normal berjalan apa
    # adanya. Di atasnya, koreksi menjauh dari bola yang lebih dekat mulai diterapkan.
    #
    # KENAPA PERLU (bug nyata di lapangan — kapal menabrak bola): steer LOCKED
    # memakai error midpoint dalam PIKSEL MUTLAK, yang tidak bisa membedakan
    # "meleset 60px di gerbang lebar 400px" (aman) dari "meleset 60px di gerbang
    # sempit 200px" (nyaris nabrak) — keduanya menghasilkan koreksi identik.
    # Guard ini menormalisasi terhadap lebar gerbang sehingga gerbang yang tampak
    # lebih sempit otomatis dikoreksi lebih agresif.
    #
    # 0.25 = boleh meleset sampai 25% dari tengah celah sebelum guard bereaksi.
    # PERLU KALIBRASI LAPANGAN: TURUNKAN kalau kapal masih menyenggol (guard jadi
    # lebih cepat bereaksi), NAIKKAN kalau kapal terlalu banyak koreksi/goyah.
    SEQ_GATE_BALANCE_DEADBAND = 0.25

    # Steer maksimum (0..1) untuk koreksi keseimbangan di atas, dicapai saat salah
    # satu bola tepat di garis haluan (imbalance ±1, paling bahaya). Sengaja LEBIH
    # BESAR dari SEQ_SINGLE_BALL_MAX_STEER (0.4) karena ini situasi tabrakan yang
    # sudah imminent (kapal sedang melintas di antara kedua bola).
    SEQ_GATE_MAX_AVOID_STEER = 0.5

    # Durasi (detik) maksimum kapal boleh maju lurus TANPA melihat kandidat pasangan
    # ATAU fallback gate_x sama sekali ("buta total"). Setelah durasi ini terlampaui,
    # kapal STOP (throttle=0) alih-alih terus maju buta — mencegah menabrak
    # tembok/keluar arena saat benar-benar tidak ada bola di frame. Dikonfirmasi
    # langsung di lapangan: tanpa batas ini, kapal bisa maju lurus TANPA HENTI.
    SEQ_BLIND_SEARCH_TIMEOUT_SEC = 5.0

    # Durasi (detik) TOTAL "buta total" (sama seperti SEQ_BLIND_SEARCH_TIMEOUT_SEC di
    # atas — tidak ada kandidat pasangan ATAU fallback gate_x sama sekali) sebelum
    # step SEQUENTIAL_BUOY dianggap SELESAI (advance ke step berikutnya / mission
    # selesai kalau ini step terakhir) — BUKAN cuma berhenti bergerak seperti
    # SEQ_BLIND_SEARCH_TIMEOUT_SEC. SENGAJA jauh lebih besar dari
    # SEQ_BLIND_SEARCH_TIMEOUT_SEC: kapal STOP dulu di 5 detik (jaring pengaman
    # tabrakan), lalu diberi jeda tambahan menunggu siapa tahu buoy sempat masuk lagi
    # ke frame (mis. kapal cuma sedikit miring), BARU dianggap benar-benar selesai
    # kalau tetap tidak ada apa pun sampai durasi ini.
    #
    # Berlaku TIDAK PEDULI apakah sudah ada pasangan yang di-cleared atau belum —
    # beda dari SEQ_SEARCHING_TIMEOUT_SEC yang HANYA aktif setelah pasangan pertama
    # berhasil dikunci. Ini mengisi celah: kalau dari AWAL step tidak ada bola
    # terdeteksi sama sekali (mis. kamera belum menghadap arah buoy, atau memang
    # buoy course sudah tidak ada), sebelumnya TIDAK ADA mekanisme apa pun yang bisa
    # menyelesaikan step ini — kapal cuma diam di HOLD selamanya menunggu input manual.
    SEQ_NO_DETECTION_FINISH_SEC = 15.0

    # Jarak PIKSEL maksimum antara bola merah & hijau agar dianggap SATU gate yang
    # sama. Ditemukan lewat pengecekan frame kamera live: kalau di frame cuma ada
    # SATU bola merah (atau hijau), filter rasio area saja TIDAK cukup — bola itu
    # akan selalu "terpilih" sebagai pasangan terdekat meski jaraknya sudah hampir
    # selebar frame kamera (mis. cluster bola hijau di kiri, satu bola merah jauh
    # di kanan). Gate asli selalu berdekatan secara piksel; pasangan yang melebar
    # seperti ini BUKAN gate valid dan menghasilkan titik tengah yang salah arah.
    # Nilai asli 200px dikalibrasi dari frame kamera live sungguhan @ 640px (bukan
    # tebakan): kasus false-pair nyata yang ditemukan berjarak ~280px, 200px memberi
    # margin aman di bawah itu. Sekarang 600px @ 1920px, kamera Logitech MX Brio,
    # diskalakan 3x linear mengikuti lebar frame. KEMUNGKINAN BESAR PERLU
    # DIKALIBRASI ULANG setelah lebih banyak data uji lapangan pada resolusi baru
    # ini (jarak kamera-ke-buoy mempengaruhi lebar gate asli dalam piksel — makin
    # dekat kamera, makin lebar gate asli tampak, sehingga threshold ini bisa jadi
    # perlu dinaikkan atau dibuat dinamis).
    SEQ_MAX_PAIR_WIDTH_PX = 600

    # ── Pair Locking / False-Pairing Prevention (Sequential Buoy) ─────────
    # Arena Sequential Buoy berbentuk LENGKUNG/ARC (gate-gate tersusun sepanjang
    # kurva, bukan garis lurus) dengan gate yang bisa berdekatan secara fisik —
    # sehingga "area bbox besar = pasti gate saat ini" TIDAK selalu berlaku semulus
    # arena garis lurus. Threshold di bawah ini sengaja dibuat KETAT (rawan
    # false-REJECT, bukan false-ACCEPT) karena konsekuensi keduanya asimetris:
    # false-reject cuma bikin re-lock lebih cepat (aman), false-accept bikin
    # kapal menabrak bola gate lain (bahaya).

    # Rasio area minimum (0..1) antara bola merah & hijau agar dianggap SATU pasangan
    # yang valid saat SEARCHING. Dua bola dari gate yang sama berada kurang lebih pada
    # jarak yang sama dari kamera → area bbox-nya mirip. Bola sisa Gate 1 (besar/dekat)
    # yang kebetulan dekat secara piksel dengan bola Gate 2 (kecil/jauh) akan ditolak
    # oleh filter ini karena rasio area-nya jauh di bawah threshold.
    SEQ_PAIR_AREA_RATIO_MIN = 0.5

    # Rasio area minimum (0..1) antara kandidat bola saat ini vs area bola yang terakhir
    # dikunci (LOCKED/TRANSITIONING), untuk validasi identitas bola per-frame.
    # Kapal terus mendekat ke Pasangan aktif → area bola yang benar TIDAK menyusut drastis
    # antar-frame. Kandidat dengan area jauh lebih kecil (mis. bola Gate 2 yang jauh)
    # ditolak meski jaraknya secara piksel masuk SEQ_IDENTITY_MAX_DIST_PX.
    SEQ_AREA_CONTINUITY_MIN_RATIO = 0.55

    # Jarak maksimum (piksel) untuk pelacakan identitas bola per-frame KHUSUS
    # SEQUENTIAL_BUOY — LEBIH KETAT dari GATE_IDENTITY_MAX_DIST_PX (900px @ 1920px)
    # milik TRACKING_BUOY, karena SEQUENTIAL_BUOY punya BANYAK gate yang bisa
    # berdekatan di arena melengkung, sehingga radius pelacakan yang longgar
    # berisiko "melompat" ke bola gate lain yang kebetulan masuk radius.
    # 450px @ 1920px (diskalakan 3x dari 150px @ 640px, kamera Logitech MX Brio).
    SEQ_IDENTITY_MAX_DIST_PX = 450

    # Radius (piksel) & durasi (detik) "zona larangan" di sekitar posisi terakhir
    # sepasang bola yang BARU SAJA dinyatakan CLEARED. Selama cooldown ini, bola
    # apa pun yang terdeteksi dekat posisi tsb DIABAIKAN sepenuhnya dari kandidat
    # pairing SEARCHING — mencegah residual/ghost detection dari gate yang baru
    # dilewati (atau bola gate berikutnya yang kebetulan sangat dekat secara
    # piksel) langsung ke-pairing salah begitu FSM kembali ke SEARCHING.
    # 450px @ 1920px (diskalakan 3x dari 150px @ 640px, kamera Logitech MX Brio).
    SEQ_CLEARED_EXCLUSION_RADIUS_PX = 450
    SEQ_CLEARED_EXCLUSION_SEC = 2.0

    # Durasi (detik) bola tersisa harus TERUS-MENERUS tidak terdeteksi sebelum dianggap
    # "confirmed hilang". Mencegah satu frame miss deteksi YOLO (flicker) langsung
    # men-trigger CLEARED prematur → reset ke SEARCHING → salah pasang dengan gate lain.
    SEQ_LOST_CONFIRM_SEC = 0.35

    # Safety-net timeout (detik) TRANSITIONING: HANYA dipakai sebagai jaring pengaman
    # terakhir jika bola tersisa TERUS terdeteksi tanpa henti (mis. false-positive statis)
    # sehingga gate tidak pernah CLEARED secara normal. Nilainya sengaja jauh lebih besar
    # dari waktu lintas gate normal agar TIDAK memaksa CLEARED saat kapal masih benar-benar
    # melintasi pasangan aktif (sesuai aturan: unlock hanya jika kedua bola confirmed hilang).
    SEQ_TRANSITIONING_SAFETY_TIMEOUT_SEC = 20.0

    # ── GYRO_FORWARD specific ───────────────────────────────────────────────
    # Durasi (detik) bola (merah/hijau apa saja) harus TERUS-MENERUS terdeteksi
    # sebelum GYRO_FORWARD dianggap "buoy ditemukan" dan step selesai lebih awal.
    # Mencegah satu frame false-positive YOLO memotong cruise sebelum benar-benar
    # sampai di depan gerbang buoy.
    GYRO_FORWARD_BALL_CONFIRM_SEC = 0.3

    # Lama GERBANG (bola merah DAN hijau bersamaan) harus terlihat TERUS-MENERUS
    # sebelum STEER_UNTIL_GATE dianggap selesai. Sama perannya dengan
    # GYRO_FORWARD_BALL_CONFIRM_SEC: satu frame false-positive YOLO tidak boleh
    # memotong manuver. Dibuat terpisah agar bisa disetel sendiri — syarat "dua warna
    # sekaligus" lebih jarang terpenuhi secara kebetulan, jadi ambang waktunya boleh
    # berbeda dari GYRO_FORWARD.
    STEER_GATE_CONFIRM_SEC = 0.3

    # Lama BOX harus terlihat TERUS-MENERUS sebelum STEER_UNTIL_BOX dianggap selesai.
    # Perannya sama dengan STEER_GATE_CONFIRM_SEC, tapi dipisah karena syaratnya lebih
    # longgar: di sana butuh DUA warna bola sekaligus (jarang terpenuhi secara
    # kebetulan), di sini cukup satu box. Syarat yang lebih mudah terpenuhi lebih
    # rentan dipicu satu frame false-positive, jadi ambangnya boleh disetel sendiri.
    STEER_BOX_CONFIRM_SEC = 0.4

    # ── PHOTO_BOX ───────────────────────────────────────────────────────────
    # Semua ambang piksel di bawah dikalibrasi pada resolusi REFERENSI (1920x1080)
    # dan diskalakan otomatis ke resolusi kamera aktual oleh _apply_resolution_scaling().
    #
    # SATU KAMERA SAJA. Box biru secara konsep adalah target bawah air dan box hijau
    # target atas air, TAPI di arena box biru masih menyembul di atas permukaan —
    # jadi keduanya dicari lewat kamera permukaan yang sama yang sudah dipakai untuk
    # tracking buoy. Tidak ada kamera underwater di sistem ini dan tidak boleh ada:
    # frame yang dipakai step ini adalah frame yang sama persis dari VideoStreamer.

    # Toleransi pemusatan (piksel dari garis tengah frame) sebelum box dianggap
    # "sudah lurus di depan haluan" dan kapal boleh mulai mendekat.
    PHOTO_ALIGN_THRESHOLD_PX = 120

    # Gain proporsional pemusatan: steer_norm penuh (±1.0) dicapai saat box berada
    # di tepi frame. SENGAJA TIDAK memakai TrackingController: PID itu di-tune untuk
    # mengejar midpoint gerbang yang bergerak cepat, dan gain-nya (lihat catatan
    # saturasi di control/pid_tracker.py) membuat kemudi bang-bang untuk target diam
    # sebesar box. Di sini yang dibutuhkan justru pendekatan yang halus dan pelan.
    PHOTO_STEER_KP = 1.0

    # Steer maksimum saat memusatkan box. Lebih kecil dari manuver gerbang: kapal
    # sedang membidik target diam, bukan menghindari tabrakan.
    PHOTO_MAX_STEER = 0.45

    # Luas bbox (piksel²) yang menandakan box sudah cukup dekat untuk difoto.
    # DIPISAH per warna dengan sengaja: box biru sebagian terendam, sehingga bagian
    # yang terlihat kamera permukaan LEBIH KECIL daripada box hijau pada jarak yang
    # sama. Memakai satu ambang untuk keduanya membuat kapal menabrak box hijau atau
    # tidak pernah merasa cukup dekat ke box biru.
    PHOTO_MIN_AREA_PX2_BLUE = 60000
    PHOTO_MIN_AREA_PX2_GREEN = 90000

    # Throttle saat meluncur mendekati box, dan saat memutar mencari box.
    PHOTO_APPROACH_THROTTLE = 0.25
    PHOTO_SEARCH_THROTTLE = 0.15

    # Steer konstan saat menyapu mencari box yang belum terlihat. Positif = kanan.
    # Arena menempatkan kedua box di sisi yang sama setelah gerbang terakhir, jadi
    # menyapu satu arah sudah cukup; ubah lewat field step kalau arenanya berbeda.
    PHOTO_SEARCH_STEER = 0.25

    # Lama kapal harus DIAM sebelum shutter ditekan. Foto yang dinilai juri diambil
    # dari kapal yang masih meluncur akan buram dan miring; jeda ini menunggu buritan
    # berhenti bergoyang lebih dulu.
    PHOTO_SETTLE_SEC = 1.2

    # Berapa lama deteksi boleh hilang sebelum kapal berhenti menganggap dirinya
    # sedang membidik. Satu-dua frame miss YOLO tidak boleh mengembalikan kapal ke
    # fase mencari — pola yang sama dipakai SEQ_LOST_CONFIRM_SEC.
    PHOTO_LOST_GRACE_SEC = 0.6

    # Batas waktu mencari SATU box sebelum menyerah dan lanjut ke target berikutnya.
    # Menyerah lebih baik daripada menahan seluruh misi demi satu foto.
    PHOTO_SEARCH_TIMEOUT_SEC = 20.0

    # Batas waktu menunggu frame kamera bersih setelah shutter diminta. Kalau kamera
    # mati, permintaan foto tidak boleh menggantung selamanya (pola yang sama dengan
    # TAKE_IMAGE).
    PHOTO_SHOOT_TIMEOUT_SEC = 3.0

    # Lama kapal menahan posisi saat PHOTO_BOX dijalankan sebelum waktunya, sebelum
    # step-nya dilewati. Lihat photo_mission() untuk alasan "tahan lalu lewati"
    # alih-alih langsung melewati atau menggantung selamanya.
    PHOTO_BLOCKED_HOLD_SEC = 10.0

    # ── BOX_CHANNEL ─────────────────────────────────────────────────────────
    # Semua ambang piksel di bawah memakai satuan resolusi REFERENSI (1920x1080) dan
    # diskalakan otomatis ke resolusi kamera aktual — sama seperti PHOTO_BOX.

    # Seberapa jauh titik lewat digeser dari SATU box yang terlihat. Inilah yang
    # membuat celah bisa disusuri walau kedua box tidak pernah terlihat bersamaan:
    # box biru menandai tepi kanan, jadi titik lewat ada sejauh ini di kirinya.
    BOXCH_CHANNEL_OFFSET_PX = 420

    # ── Offset dalam METER (cara yang disarankan) ───────────────────────────
    # Offset piksel TETAP hanya benar pada SATU jarak. Pada kamera ini 280px
    # (di 1280) berarti 0,71 m saat box berjarak 2 m, tapi 2,13 m saat 6 m —
    # di celah selebar 2 m, kapal akan membidik jauh di luar alur selama masih
    # jauh, lalu terlalu mepet begitu dekat.
    #
    # Kalau lebar box yang SEBENARNYA diketahui, offset dihitung ulang tiap frame
    # dari lebar bbox-nya: bbox yang lebar berarti box dekat berarti satu meter
    # memakan lebih banyak piksel. Perbandingannya mengkalibrasi dirinya sendiri —
    # tidak perlu tahu FOV kamera maupun jarak ke box.
    #
    #     px_per_meter = lebar_bbox_px / lebar_box_m
    #     offset_px    = px_per_meter * offset_m
    #
    # Aktif hanya kalau KEDUA field diisi (box_width_m & channel_offset_m > 0);
    # kalau tidak, jatuh ke BOXCH_CHANNEL_OFFSET_PX di atas.
    BOXCH_CHANNEL_OFFSET_M = 1.0    # setengah celah 2 m
    BOXCH_BOX_WIDTH_M = 0.0         # 0 = belum diukur → pakai offset piksel

    # Laju jelajah saat menyusuri celah, dan laju kecil saat MEMBIDIK.
    #
    # AIM_THROTTLE SENGAJA TIDAK NOL. Kemudi kapal ini memakai servo GroundSteering
    # (SERVO3/SERVO4, lihat main.py) yang butuh aliran air untuk menggigit — tanpa
    # laju sama sekali, kapal tidak berputar dan fase AIM hanya akan kehabisan waktu.
    # Kalau thruster diferensialnya ternyata sanggup memutar di tempat, turunkan
    # field `aim_throttle` ke 0 dari panel misi; tidak perlu ubah kode.
    BOXCH_TRANSIT_THROTTLE = 0.3
    BOXCH_AIM_THROTTLE = 0.08

    # Toleransi pemusatan sebelum box dianggap "sudah di tengah frame".
    BOXCH_ALIGN_THRESHOLD_PX = 140

    # Luas bbox yang menandakan box sudah cukup dekat untuk mulai dibidik. Dipisah
    # per warna: box biru sebagian terendam sehingga bagian yang terlihat kamera
    # permukaan lebih kecil pada jarak yang sama.
    BOXCH_MIN_AREA_PX2_BLUE = 45000
    BOXCH_MIN_AREA_PX2_GREEN = 70000

    # Batas waktu membidik. Lewat ini, shutter ditekan dengan framing seadanya —
    # jauh lebih baik daripada kapal merayap mendekat tanpa henti mengejar
    # pemusatan sempurna, yang berujung menyenggol box.
    BOXCH_AIM_TIMEOUT_SEC = 6.0

    BOXCH_SETTLE_SEC = 1.0

    # ── Mode "moving": memotret sambil jalan ────────────────────────────────
    # Mode "stop" (default) berhenti, memutar, diam, lalu menjepret — foto paling
    # tajam. Mode "moving" tidak pernah berhenti: memusatkan box sambil melaju,
    # menjepret, lalu MEMBANTING MENJAUH.
    #
    # Menghindar itu wajib di mode ini dan tidak ada padanannya di mode stop: di
    # sana kapal berhenti jauh dari box, di sini kapal justru sedang menuju tepat
    # ke box saat shutter ditekan. Arah menghindar TIDAK ditulis sebagai kiri/kanan
    # di sini melainkan diturunkan dari konvensi sisi — box biru menandai tepi
    # kanan, jadi menghindarnya ke kiri; hijau sebaliknya. Membalik konvensi arena
    # cukup di gate_convention.py.
    BOXCH_EVADE_SEC = 1.5
    BOXCH_EVADE_STEER = 0.45

    # Jaring pengaman jarak untuk mode moving: kalau box sudah sebesar ini kali
    # ambang "cukup dekat" dan shutter belum juga ditekan (mis. tidak pernah
    # terpusat), jepret SEKARANG dan langsung menghindar. Batas waktu membidik
    # saja tidak cukup di sini — kapal sedang melaju, jadi yang menentukan bahaya
    # adalah JARAK, bukan lamanya waktu.
    BOXCH_FORCE_SHOOT_AREA_RATIO = 2.0
    BOXCH_SHOOT_TIMEOUT_SEC = 3.0

    # Tidak ada box terlihat sama sekali: kapal maju lurus selama ini, lalu BERHENTI.
    BOXCH_BLIND_STOP_SEC = 8.0
    # Setelah sekian lama tanpa box sama sekali, step dianggap selesai.
    BOXCH_NO_DETECTION_FINISH_SEC = 20.0

    # Kedip deteksi tidak boleh langsung membatalkan bidikan.
    BOXCH_LOST_GRACE_SEC = 0.6

    # ══════════════════════════════════════════════════════════════════════
    #  BOX_APPROACH — Cari box → Dekati → Menghindar
    # ══════════════════════════════════════════════════════════════════════
    # SEMUA nilai di bawah cuma DEFAULT. Setiap satunya bisa ditimpa dari panel
    # misi lewat field step dengan nama yang tertera di komentarnya, jadi tidak
    # perlu mengedit file ini untuk tuning di danau.
    #
    # Nilai piksel & piksel² ditulis dalam satuan referensi 1920x1080 dan
    # diskalakan otomatis ke resolusi kamera aktual — lihat
    # _apply_resolution_scaling(). Jangan mengonversinya sendiri.

    # ---- Fase SCAN: mencari box ----
    BAP_SCAN_THROTTLE = 0.25        # step['scan_throttle']  laju saat menyapu mencari box
    BAP_SCAN_STEER = 0.25           # step['scan_steer']     arah & kuat sapuan.
                                    #   NEGATIF = menyapu ke KIRI, POSITIF = ke KANAN,
                                    #   0 = maju lurus tanpa menyapu. Besarnya = seberapa
                                    #   tajam belokannya (0..1).
    BAP_SCAN_TIMEOUT_SEC = 25.0     # step['scan_timeout_sec']
                                    #   Box tidak ketemu selama ini → step DISELESAIKAN,
                                    #   bukan digantung. Kapal yang menyapu tanpa batas
                                    #   akan keluar arena, dan misi yang menggantung
                                    #   tidak pernah sampai ke FINISH.

    # ---- Fase APPROACH: mendekati box ----
    BAP_APPROACH_THROTTLE = 0.25    # step['approach_throttle']  laju saat mendekat
    BAP_APPROACH_STEER_GAIN = 1.0   # step['approach_steer_gain']
                                    #   Sensitivitas pemusatan. Simpangan box dari tengah
                                    #   frame dinormalkan ke -1..+1 lalu dikali angka ini.
                                    #   Naikkan kalau kapal lambat meluruskan ke box,
                                    #   turunkan kalau kapal bergoyang kiri-kanan (osilasi).
    BAP_MAX_STEER = 0.5             # step['max_steer']
                                    #   Batas kemudi saat mendekat. Ada supaya gain yang
                                    #   kebesaran tidak berubah jadi bantingan penuh.
    BAP_MIN_DETECT_AREA_PX2 = 3000  # step['min_detect_area_px2']
                                    #   Bbox lebih kecil dari ini TIDAK dianggap box.
                                    #   Wajib ada: satu pantulan air yang lolos YOLO sudah
                                    #   cukup membuat kapal mengunci sasaran palsu di
                                    #   kejauhan dan meninggalkan alurnya.
    BAP_LOST_GRACE_SEC = 1.0        # step['lost_grace_sec']
                                    #   Box hilang sekejap (kedip deteksi) → kemudi terakhir
                                    #   dipertahankan selama ini dulu. Lewat dari ini baru
                                    #   kembali ke SCAN. Tanpa jeda ini kapal meluruskan
                                    #   haluan tiap kali YOLO berkedip.

    # ---- Pemicu menghindar ----
    BAP_CENTER_TOLERANCE_PX = 120   # step['center_tolerance_px']
                                    #   "Sudah di titik tengah" = simpangan <= ini.
    BAP_TARGET_AREA_PX2 = 45000     # step['target_area_px2']
                                    #   "Sudah dekat" = luas bbox >= ini. Inilah yang
                                    #   menentukan pada JARAK berapa kapal menghindar.
    BAP_FORCE_EVADE_AREA_RATIO = 1.8  # step['force_evade_area_ratio']
                                    #   PENGAMAN TABRAKAN. Dua syarat di atas dipakai
                                    #   bersama (DAN), jadi box yang tidak pernah benar-benar
                                    #   terpusat akan membuat kapal terus mendekat tanpa
                                    #   pernah menghindar. Begitu luasnya melewati
                                    #   target x rasio ini, kapal MENGHINDAR SEKARANG
                                    #   walau belum terpusat. Isi 0 untuk mematikan
                                    #   pengaman ini (tidak disarankan).

    # ---- Foto (opsional, default MATI) ----
    BAP_PHOTO_MODE = "off"          # step['photo']
                                    #   "off"    = tidak memotret sama sekali (default).
                                    #   "stop"   = berhenti, tunggu diam, jepret, baru
                                    #              menghindar. Foto paling tajam.
                                    #   "moving" = jepret tanpa berhenti lalu langsung
                                    #              menghindar. Lintasan tidak terputus,
                                    #              foto berisiko sedikit blur.
                                    #   Default MATI supaya step ini tetap murni soal
                                    #   manuver: menambah shutter mengubah waktu tempuh
                                    #   dan bisa mengacaukan tuning yang sudah jadi.
    BAP_PHOTO_SETTLE_SEC = 1.0      # step['photo_settle_sec']
                                    #   Lama kapal DIAM sebelum shutter, mode "stop" saja.
    BAP_SHOOT_TIMEOUT_SEC = 3.0     # Frame bersih tidak pernah datang (mis. kamera mati)
                                    #   → berhenti menunggu dan TETAP menghindar. Kapal
                                    #   sudah terlanjur mengarah ke box, dan kamera yang
                                    #   gagal bukan alasan untuk menabraknya.

    # ---- Fase EVADE: manuver menghindar ----
    BAP_EVADE_DIRECTION = "left"    # step['evade_direction']  "left"/"kiri" atau "right"/"kanan"
                                    #   Default KIRI karena box biru menandai tepi KANAN
                                    #   lintasan — menghindar ke kiri membawa kapal ke
                                    #   tengah celah, bukan keluar dari alur.
    BAP_EVADE_THROTTLE = 0.3        # step['evade_throttle']   laju saat menghindar
    BAP_EVADE_STEER = 0.5           # step['evade_steer']      kuat bantingan (0..1)
    BAP_EVADE_SEC = 2.0             # step['evade_sec']        lama manuver menghindar

    # ---- Pengaman terakhir ----
    BAP_MAX_DURATION_SEC = 90.0     # step['max_duration_sec']
                                    #   Batas keras SELURUH step, berlaku di fase mana
                                    #   pun. Ada karena scan_timeout_sec me-reset tiap
                                    #   kali kapal sempat melihat box: deteksi yang
                                    #   berkedip-kedip bisa membuat SCAN dan APPROACH
                                    #   bergantian tanpa pernah kedaluwarsa. Isi 0 untuk
                                    #   mematikan (tidak disarankan).

    # ══════════════════════════════════════════════════════════════════════
    #  DOCKING — tabrak 2 dari 3 bola biru yang berjajar
    # ══════════════════════════════════════════════════════════════════════
    # GEOMETRINYA yang menentukan seluruh rancangan step ini:
    #
    #   bola   : kiri -0,30 m │ tengah 0,00 m │ kanan +0,30 m   (rentang 0,60 m)
    #   kapal  : lebar lambung 0,40 m → setengah lambung 0,20 m
    #
    #   Lambung (0,40) lebih sempit dari rentang bola (0,60), jadi ketiganya
    #   MUSTAHIL kena sekaligus. Membidik titik tengah salah satu pasangan
    #   BERSEBELAHAN menutup tepat dua bola:
    #
    #     Opsi KIRI  → bidik -0,15 → lambung menutup [-0,35 .. +0,05] → kiri+tengah
    #     Opsi KANAN → bidik +0,15 → lambung menutup [-0,05 .. +0,35] → tengah+kanan
    #
    #   Titik bidik berjarak 0,15 m ke MASING-MASING bola sasaran, sementara
    #   setengah lambung 0,20 m. SISA TOLERANSI MELENCENG CUMA 0,05 m — plus
    #   jari-jari bola, karena lambung tidak perlu menutupi pusat bola untuk
    #   menyentuhnya. Angka 5 cm itulah alasan step ini mengunci sasarannya
    #   sekali lalu tidak berubah pikiran: pindah pasangan di tengah pendekatan
    #   berarti menggeser haluan 30 cm, dan itu enam kali lebih besar daripada
    #   seluruh toleransi yang tersedia.
    DOCK_BALL_SPACING_M = 0.30      # step['ball_spacing_m']   jarak antar pusat bola
    DOCK_BOAT_BEAM_M = 0.40         # step['boat_beam_m']      lebar lambung
    DOCK_BALL_DIAMETER_M = 0.0      # step['ball_diameter_m']
                                    #   0 = belum diukur. Kalau diisi, dipakai untuk
                                    #   memperkirakan titik bidik saat cuma SATU bola
                                    #   yang terlihat, dan untuk melaporkan toleransi
                                    #   sesungguhnya saat step dimulai.

    # ---- Pemilihan sasaran ----
    DOCK_PREFER = "auto"            # step['prefer']  "auto" | "left"/"kiri" | "right"/"kanan"
                                    #   "auto" memilih titik tengah yang PALING DEKAT
                                    #   ke haluan saat penguncian — perubahan haluan
                                    #   terkecil, jadi paling kecil peluang melenceng.
                                    #   Isi eksplisit kalau arena punya sisi yang lebih
                                    #   lapang atau juri menilai sisi tertentu.
    DOCK_LOCK_CONFIRM_SEC = 0.6     # step['lock_confirm_sec']
                                    #   Ketiga bola harus terlihat SELAMA ini sebelum
                                    #   sasaran dikunci. Satu frame nyasar yang mengunci
                                    #   sisi yang salah tidak bisa dibatalkan.
    DOCK_MIN_DETECT_AREA_PX2 = 1500 # step['min_detect_area_px2']

    # ---- Fase SEARCH ----
    DOCK_SEARCH_THROTTLE = 0.22     # step['search_throttle']
    DOCK_SEARCH_STEER = 0.2         # step['search_steer']   negatif = kiri
    DOCK_SEARCH_TIMEOUT_SEC = 30.0  # step['search_timeout_sec']

    # ---- Fase ALIGN ----
    DOCK_APPROACH_THROTTLE = 0.2    # step['approach_throttle']
    DOCK_STEER_GAIN = 1.2           # step['steer_gain']
    DOCK_MAX_STEER = 0.45           # step['max_steer']
    DOCK_ALIGN_TOLERANCE_PX = 60    # step['align_tolerance_px']
                                    #   Sengaja jauh lebih ketat daripada step lain:
                                    #   toleransi lapangannya cuma 5 cm.
    DOCK_LOST_GRACE_SEC = 0.8       # step['lost_grace_sec']

    # ---- Fase RAM ----
    DOCK_RAM_AREA_PX2 = 30000       # step['ram_area_px2']
                                    #   Luas bbola sasaran saat dianggap sudah terlalu
                                    #   dekat untuk dikoreksi lagi. Bola bakal keluar
                                    #   frame (atau tenggelam di bawah haluan) sebelum
                                    #   benturannya terjadi, jadi meter terakhir memang
                                    #   harus ditempuh tanpa penglihatan.
    DOCK_RAM_THROTTLE = 0.3         # step['ram_throttle']
    DOCK_RAM_SEC = 3.0              # step['ram_sec']

    DOCK_MAX_DURATION_SEC = 120.0   # step['max_duration_sec']

    def __init__(self, asv, tracker, tracking_controller, speed_scheduler: Optional[SpeedScheduler] = None,
                 camera_width: int = REFERENCE_FRAME_WIDTH, camera_height: int = REFERENCE_FRAME_HEIGHT):
        self.asv = asv
        self.tracker = tracker
        self.tracking_controller = tracking_controller
        self.speed_scheduler = speed_scheduler or SpeedScheduler(max_base_throttle=0.4)

        # Skalakan semua threshold berbasis piksel (GATE_IDENTITY_MAX_DIST_PX,
        # SEQ_MIN_PAIR_AREA_PX2, dkk.) dari resolusi referensi 1920x1080 ke resolusi
        # kamera AKTUAL — lihat _apply_resolution_scaling() untuk kenapa ini penting.
        # HARUS dipanggil SEBELUM state lain di bawah diinisialisasi karena beberapa
        # nilai (tidak ada saat ini, tapi jaga urutan untuk masa depan) bisa bergantung
        # padanya.
        self._apply_resolution_scaling(camera_width, camera_height)

        self._steps: List[Dict[str, Any]] = []
        self._current_step_idx: int = 0
        self._status: str = self.STATUS_IDLE

        self._lock = threading.RLock()

        # Counter berapa gate PASSING sudah terjadi di step TRACKING saat ini
        self._buoy_pass_count: int = 0

        # Gerbang sekuensi PHOTO_BOX: True setelah salah satu step buoy SELESAI
        # dalam run ini. Lihat tracking_buoy_completed dan photo_mission().
        self._tracking_buoy_completed: bool = False

        # State step PHOTO_BOX (di-reset tiap kali step-nya dimulai)
        self._photo_phase: str = self.PHOTO_SEARCH
        self._photo_phase_since: float = 0.0
        self._photo_target: Optional[str] = None
        self._photo_done: List[str] = []
        self._photo_last_seen_at: float = 0.0
        self._photo_last_steer: float = 0.0
        self._photo_blocked_since: Optional[float] = None

        # State step BOX_CHANNEL (di-reset tiap kali step-nya dimulai)
        self._boxch_phase: str = self.BOX_TRANSIT
        self._boxch_phase_since: float = 0.0
        self._boxch_target: Optional[str] = None
        self._boxch_done: List[str] = []
        self._boxch_last_seen_at: float = 0.0
        self._boxch_last_steer: float = 0.0
        self._boxch_blind_since: Optional[float] = None
        self._boxch_evade_steer: float = 0.0

        # State step BOX_APPROACH (di-reset tiap kali step-nya dimulai)
        self._bap_phase: str = self.BAP_SCAN
        self._bap_phase_since: float = 0.0
        self._bap_last_seen_at: float = 0.0
        self._bap_last_steer: float = 0.0
        self._bap_evade_steer: float = 0.0
        self._bap_evade_reason: str = ""
        self._bap_target_peran: str = ROLE_BLUE_BOX
        self._bap_shutter_diminta: bool = False
        self._bap_shutter_sejak: float = 0.0

        # State step DOCKING (di-reset tiap kali step-nya dimulai)
        self._dock_phase: str = self.DOCK_SEARCH
        self._dock_phase_since: float = 0.0
        self._dock_pilihan: Optional[str] = None   # "left" | "right", sekali kunci
        self._dock_alasan: str = ""
        self._dock_bidik_px: Optional[float] = None
        self._dock_last_steer: float = 0.0
        self._dock_last_seen_at: float = 0.0
        self._dock_bertiga_sejak: Optional[float] = None
        self._dock_ram_steer: float = 0.0
        self._dock_rasio_pasangan: float = 0.0
        # Deteksi box milik frame yang sedang diproses — lihat catatan di update_frame().
        self._frame_boxes: Dict[str, List] = {}

        # ---- Gate State Machine ----
        self._gate_lock_state: str = self.GATE_SEARCHING
        # Posisi bola yang dikunci saat state LOCKED: (cx, cy)
        self._locked_red_pos: Optional[Tuple[int, int]] = None
        self._locked_green_pos: Optional[Tuple[int, int]] = None
        # WARNA bola yang hilang duluan saat TRANSITIONING ("red"/"green").
        # Sengaja menyimpan WARNA, bukan sisi kiri/kanan: sisi diturunkan dari warna
        # lewat vision/gate_convention.py, sehingga membalik konvensi arena tidak
        # membuat state machine ini salah menunggu bola yang keliru.
        self._missing_color: Optional[str] = None
        # Steer fallback yang dipertahankan selama TRANSITIONING jika bola tersisa tidak terdeteksi
        self._transition_steer: float = 0.0
        # Timestamp saat masuk ke state LOCKED / TRANSITIONING (untuk timeout guard)
        self._gate_state_entered_at: float = 0.0
        # Timestamp saat mission di-pause dalam state LOCKED/TRANSITIONING.
        # Digunakan untuk mengkompensasi durasi pause agar timeout tidak salah tembak saat resume.
        self._gate_pause_start: float = 0.0
        # Area rata-rata (piksel²) pasangan SAAT PERTAMA KALI LOCK — TIDAK pernah
        # di-update setelahnya (beda dari posisi yang terus di-update tiap frame).
        # Dipakai GATE_LOCKED_TIMEOUT_AREA_GROWTH_MIN_RATIO untuk mendeteksi apakah
        # kapal benar-benar sudah mendekat saat LOCKED timeout tercapai.
        self._locked_entry_area: Optional[float] = None

        # ---- SEQUENTIAL_BUOY state ----
        # Semua variabel diberi prefix _seq_ agar tidak bersinggungan sama sekali
        # dengan state TRACKING_BUOY (_gate_*) yang sudah ada.
        self._seq_pairs_cleared: int = 0            # Pasangan yang sudah berhasil dilewati
        self._seq_gate_lock_state: str = self.GATE_SEARCHING
        self._seq_locked_red_pos: Optional[Tuple[int, int]] = None
        self._seq_locked_green_pos: Optional[Tuple[int, int]] = None
        # Area bbox (piksel²) terakhir dari bola yang dikunci — dipakai untuk validasi
        # identitas per-frame (SEQ_AREA_CONTINUITY_MIN_RATIO) agar bola Gate berikutnya
        # yang kebetulan dekat secara piksel tidak diambil-alih sebagai "bola yang sama".
        self._seq_locked_red_area: Optional[float] = None
        self._seq_locked_green_area: Optional[float] = None
        # Area rata-rata (piksel²) pasangan SAAT PERTAMA KALI LOCK — TIDAK pernah
        # di-update setelahnya (beda dari _seq_locked_red_area/_seq_locked_green_area
        # di atas yang di-update tiap frame untuk validasi identitas). Dipakai
        # GATE_LOCKED_TIMEOUT_AREA_GROWTH_MIN_RATIO yang sama dengan TRACKING_BUOY.
        self._seq_locked_entry_area: Optional[float] = None
        # WARNA bola yang hilang duluan (lihat _missing_color di atas).
        self._seq_missing_color: Optional[str] = None
        self._seq_transition_steer: float = 0.0
        self._seq_gate_state_entered_at: float = 0.0
        self._seq_gate_pause_start: float = 0.0
        # Timestamp saat bola tersisa PERTAMA KALI tidak terdeteksi selama TRANSITIONING.
        # None berarti bola tersisa masih terdeteksi kontinu. Dipakai untuk debounce
        # SEQ_LOST_CONFIRM_SEC sebelum gate dinyatakan CLEARED ("confirmed hilang").
        self._seq_missing_lost_since: Optional[float] = None

        # Timestamp saat SEARCHING PERTAMA KALI tidak melihat kandidat apa pun sama
        # sekali (tidak ada pasangan aman, tidak ada gate_x fallback). None berarti
        # masih ada sinyal (kandidat atau fallback). Dipakai SEQ_BLIND_SEARCH_TIMEOUT_SEC
        # agar kapal TIDAK maju lurus tanpa batas waktu saat benar-benar tidak melihat
        # bola apa pun — mencegah menabrak tembok/keluar arena.
        self._seq_blind_search_since: Optional[float] = None

        # Posisi terakhir sepasang bola yang BARU SAJA di-CLEARED (sebelum unlock) &
        # kapan itu terjadi — dipakai _filter_recently_cleared() untuk membuat "zona
        # larangan" sementara (SEQ_CLEARED_EXCLUSION_SEC) di SEARCHING, agar residual
        # detection dari gate yang baru dilewati tidak langsung ke-pairing salah
        # dengan bola gate berikutnya. SENGAJA TIDAK direset oleh
        # _reset_sequential_gate_fsm() — harus tetap hidup melewati transisi
        # CLEARED → SEARCHING agar zona larangan benar-benar berlaku di SEARCHING
        # berikutnya. Hanya direset penuh oleh _reset_sequential_state().
        self._seq_recently_cleared_red_pos: Optional[Tuple[int, int]] = None
        self._seq_recently_cleared_green_pos: Optional[Tuple[int, int]] = None
        self._seq_recently_cleared_at: float = 0.0

        # Waktu mulai step aktif & offset saat pause
        self._step_start_time: Optional[float] = None

        # ── Foto misi ber-geo-tag (step TAKE_IMAGE) ─────────────────────────
        # Engine hanya menentukan KAPAN memotret; PIKSELNYA disuplai main.py lewat
        # capture_now(), dari frame kamera yang BELUM digambari anotasi YOLO/OSD.
        # Pemisahan ini disengaja: tracker.process_frame() menggambar ke frame secara
        # in-place, jadi begitu update_frame() dipanggil, frame bersihnya sudah tidak
        # ada lagi — sementara foto yang dinilai juri harus berisi pemandangan asli,
        # bukan kotak deteksi dan label debug.
        self._capture_pending: bool = False
        self._capture_label: str = ""
        # Identitas step yang fotonya sudah diminta — pakai _step_start_time yang unik
        # tiap kali sebuah step dimasuki, supaya TAKE_IMAGE memotret SEKALI saja dan
        # tidak sekali per frame (~15x/detik selama durasi step).
        self._capture_requested_at: Optional[float] = None
        self._paused_step_elapsed: float = 0.0
        self._last_goto_time: float = 0.0

        # ---- PRECISION_TURN state ----
        # Heading awal (derajat, 0-360) saat step PRECISION_TURN dimulai.
        # Diambil dari telemetry.heading pada frame pertama step ini.
        self._turn_initial_heading: Optional[float] = None

        # Heading target (derajat, 0-360) = _turn_initial_heading + turn_angle_deg (mod 360).
        # Engine terus mengirim yaw rate hingga selisih heading <= TURN_ARRIVAL_THRESHOLD_DEG.
        self._turn_target_heading: Optional[float] = None

        # ---- GYRO_FORWARD state ----
        # Heading yang DIPERTAHANKAN (heading-hold) selama cruise — direkam dari
        # telemetry.heading pada frame pertama step ini, BUKAN yaw rate konstan tanpa
        # feedback seperti CUSTOM_FORWARD. Setiap frame, error terhadap heading ini
        # dikoreksi proporsional (lihat _handle_gyro_forward).
        self._cruise_initial_heading: Optional[float] = None

        # Timestamp saat bola (merah/hijau apa saja) PERTAMA KALI terdeteksi kontinu
        # selama GYRO_FORWARD. None berarti tidak ada bola terlihat saat ini. Dipakai
        # debounce GYRO_FORWARD_BALL_CONFIRM_SEC sebelum step dianggap selesai karena
        # gerbang buoy sudah terlihat.
        self._cruise_ball_seen_since: Optional[float] = None
        # Sejak kapan GERBANG (merah+hijau) terlihat kontinu pada STEER_UNTIL_GATE.
        # SENGAJA terpisah dari _cruise_ball_seen_since: kalau dipakai bersama, sisa
        # hitungan dari step GYRO_FORWARD sebelumnya bisa langsung menyelesaikan step
        # ini di frame pertama.
        self._steer_gate_seen_since: Optional[float] = None
        self._steer_box_seen_since: Optional[float] = None

        # Callback → kirim status live ke Base Station via WebSocket
        self._status_callback = None

        # Timestamp mulai mission
        self._mission_start_time: Optional[float] = None
        self._elapsed_sec: int = 0

        self._elapsed_thread: Optional[threading.Thread] = None
        self._elapsed_running: bool = False

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def set_status_callback(self, cb):
        """Daftarkan callback fn(status_dict) untuk broadcast status ke WS."""
        self._status_callback = cb

    def load_mission(self, steps: List[Dict[str, Any]]) -> bool:
        """Load mission steps dari JSON array. Return True jika valid."""
        with self._lock:
            if self._status == self.STATUS_RUNNING:
                print("[MissionEngine] Tidak bisa load mission saat RUNNING!")
                return False
            self._steps = list(steps)
            self._current_step_idx = 0
            self._status = self.STATUS_IDLE
            self._buoy_pass_count = 0
            self._reset_gate_state_machine()
            self._reset_sequential_state()
            self._step_start_time = None
            self._paused_step_elapsed = 0.0
            # Gerbang sekuensi PHOTO_BOX: run baru berarti step buoy-nya harus
            # diselesaikan lagi dari awal sebelum boleh memotret.
            self._tracking_buoy_completed = False
            self._reset_photo_state()
            self._reset_boxch_state()
            print(f"[MissionEngine] Mission loaded: {len(self._steps)} steps.")
            self._broadcast_status()
            return True

    def start_mission(self, steps: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Mulai eksekusi mission (bisa sekaligus load steps jika diberikan)."""
        with self._lock:
            if steps:
                self._steps = list(steps)
                self._current_step_idx = 0
                self._buoy_pass_count = 0
                self._reset_gate_state_machine()
                self._reset_sequential_state()
                self._step_start_time = None
                self._paused_step_elapsed = 0.0
                print(f"[MissionEngine] Mission loaded: {len(self._steps)} steps.")

            if not self._steps:
                print("[MissionEngine] Tidak ada mission steps yang di-load!")
                return False
            if self._status == self.STATUS_RUNNING:
                print("[MissionEngine] Mission sudah RUNNING!")
                return False

            # Hentikan elapsed timer lama agar tidak ada thread ganda saat restart
            self._stop_elapsed_timer()

            self._status = self.STATUS_RUNNING
            self._current_step_idx = 0
            self._buoy_pass_count = 0
            self._reset_gate_state_machine()
            self._reset_sequential_state()
            self._step_start_time = None
            self._paused_step_elapsed = 0.0
            self._last_goto_time = 0.0
            self._mission_start_time = time.time()
            self._elapsed_sec = 0
            # Reset PRECISION_TURN state agar bisa dipakai ulang dari awal
            self._turn_initial_heading = None
            self._turn_target_heading  = None
            # Reset GYRO_FORWARD state agar bisa dipakai ulang dari awal
            self._cruise_initial_heading = None
            self._cruise_ball_seen_since = None
            self._steer_gate_seen_since = None
            self._steer_box_seen_since = None
            # Gerbang sekuensi PHOTO_BOX: run baru berarti step buoy-nya harus
            # diselesaikan lagi dari awal sebelum boleh memotret.
            self._tracking_buoy_completed = False
            self._reset_photo_state()
            self._reset_boxch_state()

            if hasattr(self.tracking_controller, 'reset'):
                self.tracking_controller.reset()

            self._start_elapsed_timer()
            print(f"[MissionEngine]  MISSION STARTED! ({len(self._steps)} steps)")
            self._broadcast_status()
            return True

    def pause_mission(self):
        """Pause mission (ASV berhenti di posisi)."""
        with self._lock:
            if self._status != self.STATUS_RUNNING:
                return
            self._status = self.STATUS_PAUSED
            if self._step_start_time:
                self._paused_step_elapsed += time.time() - self._step_start_time
                self._step_start_time = None
            # Debounce berbasis timestamp WAJIB dilupakan saat pause: kalau tidak,
            # lama waktu pause ikut terhitung sebagai "terlihat kontinu" dan step
            # langsung selesai di frame pertama setelah resume.
            self._cruise_ball_seen_since = None
            self._steer_gate_seen_since = None
            self._steer_box_seen_since = None
            # Simpan timestamp pause gate timer agar timeout tidak salah tembak saat resume.
            # Tanpa ini, jika paused >8s saat LOCKED maka resume langsung timeout → SEARCHING.
            if (self._gate_lock_state in (self.GATE_LOCKED, self.GATE_TRANSITIONING)
                    and self._gate_state_entered_at > 0):
                self._gate_pause_start = time.time()
            # Kompensasi juga untuk Sequential Buoy gate FSM
            # Termasuk GATE_SEARCHING agar timeout SEARCHING tidak salah tembak saat resume.
            if (self._seq_gate_lock_state in (self.GATE_SEARCHING, self.GATE_LOCKED, self.GATE_TRANSITIONING)
                    and self._seq_gate_state_entered_at > 0):
                self._seq_gate_pause_start = time.time()
            self._stop_elapsed_timer()
            self.asv.stop_movement()
            print(f"[MissionEngine] ⏸ MISSION PAUSED (Step elapsed: {self._paused_step_elapsed:.1f}s).")
            self._broadcast_status()

    def resume_mission(self):
        """Resume mission dari paused."""
        with self._lock:
            if self._status != self.STATUS_PAUSED:
                return
            self._status = self.STATUS_RUNNING
            self._step_start_time = time.time() - self._paused_step_elapsed
            # Kompensasi gate timer: geser entered_at maju sebesar durasi pause
            # sehingga timeout dihitung dari waktu aktif saja, bukan termasuk waktu pause.
            if self._gate_pause_start > 0 and self._gate_state_entered_at > 0:
                paused_duration = time.time() - self._gate_pause_start
                self._gate_state_entered_at += paused_duration
                self._gate_pause_start = 0.0
            # Kompensasi juga untuk Sequential Buoy gate FSM
            if self._seq_gate_pause_start > 0 and self._seq_gate_state_entered_at > 0:
                paused_duration = time.time() - self._seq_gate_pause_start
                self._seq_gate_state_entered_at += paused_duration
                self._seq_gate_pause_start = 0.0
                # Geser juga timer debounce "confirmed hilang" agar durasi pause tidak
                # ikut terhitung sebagai waktu bola tersisa tidak terdeteksi.
                if self._seq_missing_lost_since is not None:
                    self._seq_missing_lost_since += paused_duration
            self._start_elapsed_timer()
            print("[MissionEngine]  MISSION RESUMED.")
            self._broadcast_status()

    def abort_mission(self):
        """Batalkan mission dan stop kapal."""
        with self._lock:
            self._status = self.STATUS_ABORTED
            self._stop_elapsed_timer()
            self.asv.stop_movement()
            print("[MissionEngine]  MISSION ABORTED!")
            self._broadcast_status()

    def reset_mission(self):
        """Reset semua state ke IDLE."""
        with self._lock:
            self._status = self.STATUS_IDLE
            self._current_step_idx = 0
            self._buoy_pass_count = 0
            self._step_start_time = None
            self._paused_step_elapsed = 0.0
            self._elapsed_sec = 0
            self._reset_gate_state_machine()
            self._reset_sequential_state()
            # Reset PRECISION_TURN state
            self._turn_initial_heading = None
            self._turn_target_heading  = None
            # Reset GYRO_FORWARD state
            self._cruise_initial_heading = None
            self._cruise_ball_seen_since = None
            self._steer_gate_seen_since = None
            self._steer_box_seen_since = None
            # Gerbang sekuensi PHOTO_BOX: run baru berarti step buoy-nya harus
            # diselesaikan lagi dari awal sebelum boleh memotret.
            self._tracking_buoy_completed = False
            self._reset_photo_state()
            self._reset_boxch_state()
            self._stop_elapsed_timer()
            self.asv.stop_movement()
            if hasattr(self.tracking_controller, 'reset'):
                self.tracking_controller.reset()
            print("[MissionEngine] 🔄 MISSION RESET.")
            self._broadcast_status()

    @property
    def status(self) -> str:
        return self._status

    @property
    def gate_lock_state(self) -> str:
        """Expose gate state machine state untuk OSD di tracker."""
        return self._gate_lock_state

    @property
    def current_step_id(self) -> int:
        with self._lock:
            if self._steps and self._current_step_idx < len(self._steps):
                return self._steps[self._current_step_idx].get("id", self._current_step_idx + 1)
            return 0

    def get_status_dict(self) -> Dict[str, Any]:
        with self._lock:
            current_step_info = {}
            if self._steps and self._current_step_idx < len(self._steps):
                current_step_info = self._steps[self._current_step_idx]

            step_elapsed = 0.0
            if self._status == self.STATUS_RUNNING and self._step_start_time is not None:
                step_elapsed = round(time.time() - self._step_start_time, 1)
            elif self._status == self.STATUS_PAUSED:
                step_elapsed = round(self._paused_step_elapsed, 1)

            return {
                "status": self._status,
                "current_step_idx": self._current_step_idx,
                "current_step": current_step_info,
                "total_steps": len(self._steps),
                "elapsed_sec": self._elapsed_sec,
                "step_elapsed_sec": max(0.0, step_elapsed),
                "buoy_pass_count": self._buoy_pass_count,
                "gate_lock_state": self._gate_lock_state,
                "seq_current_pair": self._seq_pairs_cleared + 1,
                "seq_pairs_cleared": self._seq_pairs_cleared,
                "seq_gate_lock_state": self._seq_gate_lock_state,
                # PHOTO_BOX — supaya operator bisa melihat kenapa kapal diam
                # (mencari? menunggu diam? diblokir gerbang sekuensi?)
                "tracking_buoy_completed": self._tracking_buoy_completed,
                "photo_phase": self._photo_phase,
                "photo_target": self._photo_target,
                "photo_done": list(self._photo_done),
                "boxch_phase": self._boxch_phase,
                "boxch_target": self._boxch_target,
                "boxch_done": list(self._boxch_done),
                # BOX_APPROACH — operator perlu tahu kapal sedang mencari, mendekat,
                # atau sudah menghindar, dan APA yang memicu menghindarnya.
                "bap_phase": self._bap_phase,
                "bap_evade_reason": self._bap_evade_reason,
                # DOCKING — sisi mana yang dikunci adalah satu-satunya keputusan
                # yang tidak bisa dibatalkan di step ini, jadi harus terlihat operator.
                "dock_phase": self._dock_phase,
                "dock_pilihan": self._dock_pilihan,
                "dock_alasan": self._dock_alasan,
            }

    # ------------------------------------------------------------------ #
    #  Frame Update Loop (dipanggil dari video_streamer callback ~30FPS)  #
    # ------------------------------------------------------------------ #

    def update_frame(self, frame, gate_x: Optional[float], detected_balls: Optional[Dict] = None,
                     detected_boxes: Optional[Dict] = None):
        """
        Dipanggil oleh process_and_control() setiap frame.

        :param frame:          Frame kamera saat ini.
        :param gate_x:         Koordinat X midpoint gate dari tracker (fallback/visual).
        :param detected_balls: Dict {"red": [...], "green": [...]} dari tracker.process_frame().
                               Masing-masing berisi list (cx, cy, x1, y1, x2, y2).
        :param detected_boxes: Dict {"blue_box": [...], "green_box": [...]}, format sama.
                               Hanya dipakai step PHOTO_BOX. Opsional agar pemanggil lama
                               (mis. tools/buoy_sim.py) tetap jalan tanpa perubahan.

        Return: (steer_norm, thr_norm, step_type_label)
        """
        with self._lock:
            # Simpan deteksi box milik FRAME INI. Beberapa handler menyelesaikan
            # step-nya lalu memanggil update_frame() lagi secara rekursif dengan
            # argumen lama (frame, gate_x, detected_balls) — tanpa simpanan ini,
            # step PHOTO_BOX yang mulai lewat jalur rekursi itu akan melihat nol box
            # padahal box-nya ada di frame. Hanya ditimpa saat pemanggil benar-benar
            # memberi nilai, sehingga rekursi mewarisi milik frame yang sama.
            if detected_boxes is not None:
                self._frame_boxes = detected_boxes

            if self._status != self.STATUS_RUNNING:
                return 0.0, 0.0, "IDLE"

            if self._current_step_idx >= len(self._steps):
                self._finish_mission()
                return 0.0, 0.0, "FINISH"

            step = self._steps[self._current_step_idx]
            step_type = step.get("type", "")

            # Inisialisasi timer & state saat baru masuk ke langkah ini
            if self._step_start_time is None:
                self._step_start_time = time.time() - self._paused_step_elapsed
                if step_type == self.STEP_TYPE_TRACKING_BUOY:
                    if hasattr(self.tracking_controller, 'reset'):
                        self.tracking_controller.reset()
                    self._reset_gate_state_machine()
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch Flight Controller mode -> MANUAL for TRACKING_BUOY...")
                        self.asv.set_mode("MANUAL")
                elif step_type in (self.STEP_TYPE_TIMED_STEER, self.STEP_TYPE_STEER_UNTIL_GATE,
                                   self.STEP_TYPE_STEER_UNTIL_BOX):
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print(f"[MissionEngine] 🔄 Switch mode → MANUAL untuk {step_type}...")
                        self.asv.set_mode("MANUAL")
                elif step_type in (self.STEP_TYPE_SEQUENTIAL_BUOY, self.STEP_TYPE_BUOY_CHASE):
                    # BUOY_CHASE memakai state _seq_* & handler yang SAMA dengan
                    # SEQUENTIAL_BUOY (lihat _handle_buoy_chase) — harus di-reset sama
                    # persis saat step manapun dari keduanya baru dimulai.
                    if hasattr(self.tracking_controller, 'reset'):
                        self.tracking_controller.reset()
                    self._reset_sequential_state()
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print(f"[MissionEngine] 🔄 Switch mode → MANUAL untuk {step_type}...")
                        self.asv.set_mode("MANUAL")
                elif step_type == self.STEP_TYPE_BOX_CHANNEL:
                    # Mode MANUAL + RC override: menyusuri celah butuh kemudi yang
                    # merespons per frame, bukan velocity GUIDED yang dihaluskan.
                    self._reset_boxch_state()
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch mode → MANUAL untuk BOX_CHANNEL...")
                        self.asv.set_mode("MANUAL")

                elif step_type == self.STEP_TYPE_DOCKING:
                    # MANUAL + RC override: toleransi melencengnya cuma 5 cm, jadi
                    # kemudi harus merespons per frame, bukan lewat velocity GUIDED
                    # yang dihaluskan autopilot.
                    self._reset_dock_state()
                    self._dock_laporkan_geometri(step)
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch mode → MANUAL untuk DOCKING...")
                        self.asv.set_mode("MANUAL")

                elif step_type == self.STEP_TYPE_BOX_APPROACH:
                    # Mode MANUAL + RC override: memusatkan box butuh kemudi yang
                    # merespons per frame, bukan velocity GUIDED yang dihaluskan.
                    self._reset_bap_state()
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch mode → MANUAL untuk BOX_APPROACH...")
                        self.asv.set_mode("MANUAL")

                elif step_type == self.STEP_TYPE_PHOTO_BOX:
                    # Mode MANUAL + RC override, sama seperti step berbasis kamera
                    # lainnya: pemusatan box butuh kemudi yang merespons per frame,
                    # bukan velocity GUIDED yang dihaluskan autopilot.
                    self._reset_photo_state()
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch mode → MANUAL untuk PHOTO_BOX...")
                        self.asv.set_mode("MANUAL")

                elif step_type == self.STEP_TYPE_GYRO_FORWARD:
                    # SAMA seperti TRACKING_BUOY/SEQUENTIAL_BUOY/TIMED_STEER — mode MANUAL,
                    # gerak via RC Override (send_manual_rc_drive), BUKAN GUIDED/send_velocity.
                    # Konsepnya identik dgn TRACKING_BUOY, hanya sumber error steering-nya
                    # yang beda: heading kompas/gyro, bukan posisi bola di kamera.
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch mode → MANUAL untuk GYRO_FORWARD...")
                        self.asv.set_mode("MANUAL")
                elif step_type in (self.STEP_TYPE_HOLD, self.STEP_TYPE_TAKE_IMAGE):
                    # Pastikan mode GUIDED agar stop_movement() (send_velocity 0) efektif
                    if self.asv and self.asv.is_connected():
                        telemetry = self.asv.get_telemetry()
                        if telemetry.mode != "GUIDED":
                            print(f"[MissionEngine] 🔄 Switch mode → GUIDED untuk {step_type}...")
                            self.asv.set_mode("GUIDED")
                    self.asv.stop_movement()
                elif step_type in (self.STEP_TYPE_CUSTOM_FORWARD, self.STEP_TYPE_PRECISION_TURN):
                    # Switch ke GUIDED dan lepaskan RC override dari step MANUAL sebelumnya
                    if self.asv and self.asv.is_connected():
                        if self.asv.get_telemetry().mode != "GUIDED":
                            print(f"[MissionEngine] 🔄 Switch mode → GUIDED untuk {step_type}...")
                            self.asv.set_mode("GUIDED")
                        self.asv.release_rc()

            # ---- TRACKING_BUOY ----
            if step_type == self.STEP_TYPE_TRACKING_BUOY:
                return self._handle_tracking(step, gate_x, detected_balls or {"red": [], "green": []})

            # ---- GOTO_GPS ----
            elif step_type == self.STEP_TYPE_GOTO_GPS:
                return self._handle_goto_gps(step, frame, gate_x, detected_balls)

            # ---- TAKE_IMAGE ----
            elif step_type == self.STEP_TYPE_TAKE_IMAGE:
                return self._handle_take_image(step, frame, gate_x, detected_balls)

            # ---- HOLD ----
            elif step_type == self.STEP_TYPE_HOLD:
                return self._handle_hold(step, frame, gate_x, detected_balls)

            # ---- START (warmup sebentar) ----
            elif step_type == self.STEP_TYPE_START:
                warmup_sec = self._safe_float(step.get("duration_sec"), 2.0)
                if time.time() - self._step_start_time >= warmup_sec:
                    self._advance_step()
                    return self.update_frame(frame, gate_x, detected_balls)
                return 0.0, 0.0, "START"

            # ---- CUSTOM_FORWARD ----
            elif step_type == self.STEP_TYPE_CUSTOM_FORWARD:
                return self._handle_custom_forward(step)

            # ---- PRECISION_TURN ----
            elif step_type == self.STEP_TYPE_PRECISION_TURN:
                return self._handle_precision_turn(step)

            # ---- TIMED_STEER ----
            elif step_type == self.STEP_TYPE_TIMED_STEER:
                return self._handle_timed_steer(step)

            # ---- STEER_UNTIL_GATE ----
            elif step_type == self.STEP_TYPE_STEER_UNTIL_GATE:
                return self._handle_steer_until_gate(
                    step, detected_balls or {"red": [], "green": []})

            # ---- SEQUENTIAL_BUOY ----
            elif step_type == self.STEP_TYPE_SEQUENTIAL_BUOY:
                return self._handle_sequential_buoy(step, gate_x, detected_balls or {"red": [], "green": []})

            # ---- GYRO_FORWARD ----
            elif step_type == self.STEP_TYPE_GYRO_FORWARD:
                return self._handle_gyro_forward(step, detected_balls or {"red": [], "green": []})

            # ---- BUOY_CHASE ----
            elif step_type == self.STEP_TYPE_BUOY_CHASE:
                return self._handle_buoy_chase(step, gate_x, detected_balls or {"red": [], "green": []})

            # ---- STEER_UNTIL_BOX ----
            elif step_type == self.STEP_TYPE_STEER_UNTIL_BOX:
                return self._handle_steer_until_box(step, self._frame_boxes)

            # ---- PHOTO_BOX ----
            elif step_type == self.STEP_TYPE_PHOTO_BOX:
                return self._handle_photo_box(step, frame, gate_x, detected_balls,
                                              self._frame_boxes)

            # ---- DOCKING ----
            elif step_type == self.STEP_TYPE_DOCKING:
                return self._handle_docking(step, frame, gate_x, detected_balls)

            # ---- BOX_APPROACH ----
            elif step_type == self.STEP_TYPE_BOX_APPROACH:
                return self._handle_box_approach(step, frame, gate_x, detected_balls,
                                                 self._frame_boxes)

            # ---- BOX_CHANNEL ----
            elif step_type == self.STEP_TYPE_BOX_CHANNEL:
                return self._handle_box_channel(step, frame, gate_x, detected_balls,
                                                self._frame_boxes)

            # ---- FINISH ----
            elif step_type == self.STEP_TYPE_FINISH:
                self._finish_mission()
                return 0.0, 0.0, "FINISH"

            else:
                # Unknown step — skip
                self._advance_step()
                return self.update_frame(frame, gate_x, detected_balls)

    # ------------------------------------------------------------------ #
    #  Step Handlers                                                      #
    # ------------------------------------------------------------------ #

    def _handle_tracking(self, step, gate_x: Optional[float], detected_balls: Dict):
        """
        Handle TRACKING_BUOY step menggunakan Gate State Machine.

        State Machine:
          SEARCHING    → Mencari pasangan bola. Gunakan gate_x fallback dari tracker.
          LOCKED       → Pasangan bola dikunci. PID ke midpoint locked pair.
          TRANSITIONING → Satu bola hilang. Manuver condong, DILARANG pair ulang.
          CLEARED      → Kedua bola hilang. Gate terlewati, reset ke SEARCHING.

        Kasus khusus LOCKED timeout (GATE_LOCKED_TIMEOUT_SEC, 8s): kalau kedua bola
        MASIH terlihat terus-menerus melewati durasi ini (kamera/FOV tidak membuat
        bola keluar frame walau kapal sudah lewat), dicek area pasangan sudah
        membesar sejak lock pertama atau belum (lihat GATE_LOCKED_TIMEOUT_AREA_
        GROWTH_MIN_RATIO). Membesar signifikan → dihitung sebagai 1 pass valid.
        Tidak membesar (kapal diam menatap dari jauh) → reset tanpa hitungan seperti
        semula. `locked_timeout_area_growth_min_ratio` (step field, opsional)
        override rasio pertumbuhan minimumnya.
        """
        target_pass_count = self._safe_int(step.get("pass_count"), 0)
        duration = self._safe_float(step.get("duration_sec"), 0.0)

        # --- Cek kondisi selesai berdasarkan pass_count ---
        if target_pass_count > 0 and self._buoy_pass_count >= target_pass_count:
            print(f"[MissionEngine] ✅ TRACKING_BUOY selesai! Pass count: {self._buoy_pass_count}/{target_pass_count}")
            self._reset_gate_state_machine()
            self._advance_step()
            return 0.0, 0.0, "TRACKING_BUOY"

        # --- Cek kondisi selesai berdasarkan duration ---
        if target_pass_count == 0 and duration > 0 and self._step_start_time and (time.time() - self._step_start_time >= duration):
            print(f"[MissionEngine] ✅ TRACKING_BUOY selesai! Durasi {duration}s terpenuhi.")
            self._reset_gate_state_machine()
            self._advance_step()
            return 0.0, 0.0, "TRACKING_BUOY"

        # Pastikan FC selalu berada di mode MANUAL saat menjalankan TRACKING_BUOY
        if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
            print("[MissionEngine] 🔄 Automatic mode switch to MANUAL for TRACKING_BUOY...")
            self.asv.set_mode("MANUAL")

        red_visible   = len(detected_balls.get("red", [])) > 0
        green_visible = len(detected_balls.get("green", [])) > 0
        throttle      = self._resolve_step_throttle(step)

        pass_label = f"{self._buoy_pass_count}/{target_pass_count}" if target_pass_count > 0 else str(self._buoy_pass_count)

        # ══════════════════════════════════════════════════════
        #  GATE STATE MACHINE
        # ══════════════════════════════════════════════════════

        if self._gate_lock_state == self.GATE_SEARCHING:
            # ── SEARCHING ──────────────────────────────────────
            if red_visible and green_visible:
                # Kedua bola terlihat → LOCK pasangan
                closest_red   = detected_balls["red"][0]    # sorted foreground-first
                closest_green = detected_balls["green"][0]
                self._locked_red_pos   = (closest_red[0],   closest_red[1])
                self._locked_green_pos = (closest_green[0], closest_green[1])
                self._locked_entry_area = self._pair_avg_area(closest_red, closest_green)
                self._gate_lock_state  = self.GATE_LOCKED
                self._gate_state_entered_at = time.time()
                print(f"[GATE] SEARCHING → LOCKED "
                      f"(red=({self._locked_red_pos}), green=({self._locked_green_pos}), "
                      f"entry_area={self._locked_entry_area:.0f}px²)")

                # Hitung steer ke midpoint locked pair
                locked_midpoint_x = (self._locked_red_pos[0] + self._locked_green_pos[0]) // 2
                steer = self.tracking_controller.compute_normalized_steering(locked_midpoint_x)
                label = f"GATE:LOCKED | TRACKING_BUOY ({pass_label} pass)"
                return steer, throttle, label

            else:
                # Belum ada pasangan → gunakan gate_x fallback dari tracker
                if gate_x is not None:
                    steer = self.tracking_controller.compute_normalized_steering(gate_x)
                    label = f"GATE:SEARCHING | TRACKING_BUOY ({pass_label} pass)"
                    return steer, throttle, label
                else:
                    # Tidak ada target sama sekali → tetap maju lurus pelan agar tidak stuck diam
                    # Kapal terus bergerak maju sehingga buoy masuk frame kembali
                    label = f"GATE:SEARCHING (no target) | TRACKING_BUOY ({pass_label} pass)"
                    return 0.0, throttle, label

        elif self._gate_lock_state == self.GATE_LOCKED:
            # ── LOCKED ────────────────────────────────────────
            # Pastikan bola merah/hijau yang terdeteksi masih "bola yang sama"
            nearest_red = self._find_nearest_ball(detected_balls.get("red", []), self._locked_red_pos)
            nearest_green = self._find_nearest_ball(detected_balls.get("green", []), self._locked_green_pos)
            
            red_visible_locked = nearest_red is not None
            green_visible_locked = nearest_green is not None

            # ── Timeout guard: jika terlalu lama LOCKED tanpa bola hilang, kembali ke SEARCHING
            # KECUALI area pasangan sudah membesar signifikan sejak lock pertama kali —
            # itu bukti kapal BENAR mendekat (bukan cuma diam menghadap gate dari jauh),
            # sehingga kamera/FOV kemungkinan besar memang tidak membuat bola keluar
            # frame saat kapal lewat (gerbang sempit, kamera bersudut lebar, dst).
            # Dalam kasus itu, hitung sebagai 1 pass VALID alih-alih reset diam-diam
            # tanpa hitungan (lihat GATE_LOCKED_TIMEOUT_AREA_GROWTH_MIN_RATIO).
            now = time.time()
            locked_duration = now - self._gate_state_entered_at
            if locked_duration > self.GATE_LOCKED_TIMEOUT_SEC and red_visible_locked and green_visible_locked:
                growth_ratio = self._safe_float(
                    step.get("locked_timeout_area_growth_min_ratio"),
                    self.GATE_LOCKED_TIMEOUT_AREA_GROWTH_MIN_RATIO)
                current_area = self._pair_avg_area(nearest_red, nearest_green)
                area_grew_enough = (
                    self._locked_entry_area is not None and self._locked_entry_area > 0
                    and current_area >= self._locked_entry_area * growth_ratio
                )
                if area_grew_enough:
                    print(f"[GATE] LOCKED TIMEOUT ({locked_duration:.1f}s) TAPI area membesar "
                          f"{current_area:.0f}px² (dari {self._locked_entry_area:.0f}px² saat lock, "
                          f"rasio {current_area / self._locked_entry_area:.2f}x) → anggap SUDAH LEWAT, "
                          f"hitung sebagai pass.")
                    self._gate_lock_state = self.GATE_CLEARED
                    return self._handle_gate_cleared(pass_label, step)
                else:
                    entry_area_label = f"{self._locked_entry_area:.0f}" if self._locked_entry_area else "?"
                    print(f"[GATE] LOCKED TIMEOUT ({locked_duration:.1f}s), area TIDAK membesar cukup "
                          f"({current_area:.0f}px² vs {entry_area_label}px² saat lock) → SEARCHING "
                          f"(reset, bukan pass valid).")
                    self._reset_gate_state_machine()
                    label = f"GATE:SEARCHING (timeout) | TRACKING_BUOY ({pass_label} pass)"
                    return 0.0, throttle, label

            if red_visible_locked and green_visible_locked:
                # Kedua bola masih terlihat → update posisi locked pair (supaya smooth tracking)
                self._locked_red_pos   = (nearest_red[0],   nearest_red[1])
                self._locked_green_pos = (nearest_green[0], nearest_green[1])

                locked_midpoint_x = (self._locked_red_pos[0] + self._locked_green_pos[0]) // 2
                steer = self.tracking_controller.compute_normalized_steering(locked_midpoint_x)
                label = f"GATE:LOCKED | TRACKING_BUOY ({pass_label} pass)"
                return steer, throttle, label

            elif not red_visible_locked and green_visible_locked:
                # ★ Bola MERAH hilang duluan → condong ke SISI MERAH (lihat konvensi)
                self._missing_color    = "red"
                self._gate_lock_state  = self.GATE_TRANSITIONING
                self._gate_state_entered_at = time.time()
                # Update posisi terakhir bola hijau yang terlihat
                self._locked_green_pos = (nearest_green[0], nearest_green[1])
                # Steer PAKSA konstan — pertahankan sampai bola hijau juga hilang.
                self._transition_steer = self._lean_steer_for_missing(
                    "red", self.TRANSITION_LEAN_MAGNITUDE)
                print(f"[GATE] LOCKED → TRANSITIONING (missing=red/{side_of('red').upper()}, "
                      f"lean={self._transition_steer:+.2f})")
                label = (f"GATE:TRANSITIONING({self._lean_arrow('red')}) "
                         f"| TRACKING_BUOY ({pass_label} pass)")
                return self._transition_steer, throttle, label

            elif red_visible_locked and not green_visible_locked:
                # ★ Bola HIJAU hilang duluan → condong ke SISI HIJAU (lihat konvensi)
                self._missing_color    = "green"
                self._gate_lock_state  = self.GATE_TRANSITIONING
                self._gate_state_entered_at = time.time()
                # Update posisi terakhir bola merah yang terlihat
                self._locked_red_pos   = (nearest_red[0], nearest_red[1])
                # Steer PAKSA konstan — pertahankan sampai bola merah juga hilang.
                self._transition_steer = self._lean_steer_for_missing(
                    "green", self.TRANSITION_LEAN_MAGNITUDE)
                print(f"[GATE] LOCKED → TRANSITIONING (missing=green/{side_of('green').upper()}, "
                      f"lean={self._transition_steer:+.2f})")
                label = (f"GATE:TRANSITIONING({self._lean_arrow('green')}) "
                         f"| TRACKING_BUOY ({pass_label} pass)")
                return self._transition_steer, throttle, label

            else:
                # Kedua bola hilang sekaligus dari LOCKED → langsung CLEARED
                self._gate_lock_state = self.GATE_CLEARED
                print("[GATE] LOCKED → CLEARED (kedua bola hilang bersamaan)")
                return self._handle_gate_cleared(pass_label, step)

        elif self._gate_lock_state == self.GATE_TRANSITIONING:
            # ── TRANSITIONING ─────────────────────────────────
            # Periksa apakah bola yang TERSISA (bukan yang hilang) masih terlihat.
            # DILARANG KERAS memperhitungkan bola dari gerbang berikutnya.
            remaining_visible = False
            
            if self._missing_color == "red":
                # Bola merah sudah hilang, tinggal tunggu bola hijau juga hilang.
                nearest_green = self._find_nearest_ball(detected_balls.get("green", []), self._locked_green_pos)
                if nearest_green:
                    remaining_visible = True
                    self._locked_green_pos = (nearest_green[0], nearest_green[1])
                    # Steer tetap PAKSA konstan selama bola hijau masih terlihat — TIDAK
                    # mengikuti posisi bola hijau di layar (lihat TRANSITION_LEAN_MAGNITUDE).
                    self._transition_steer = self._lean_steer_for_missing(
                        "red", self.TRANSITION_LEAN_MAGNITUDE)
            elif self._missing_color == "green":
                # Bola hijau sudah hilang, tinggal tunggu bola merah juga hilang.
                nearest_red = self._find_nearest_ball(detected_balls.get("red", []), self._locked_red_pos)
                if nearest_red:
                    remaining_visible = True
                    self._locked_red_pos = (nearest_red[0], nearest_red[1])
                    # Steer tetap PAKSA konstan selama bola merah masih terlihat.
                    self._transition_steer = self._lean_steer_for_missing(
                        "green", self.TRANSITION_LEAN_MAGNITUDE)

            # ── Timeout guard TRANSITIONING ───────────────────
            # Jika terlalu lama di TRANSITIONING (bola tersisa terus terlihat), paksa CLEARED.
            # Ini handle kasus bola dari gerbang BERIKUTNYA masuk frame sebelum bola ini hilang.
            transitioning_duration = time.time() - self._gate_state_entered_at
            if transitioning_duration > self.GATE_TRANSITIONING_TIMEOUT_SEC:
                print(f"[GATE] TRANSITIONING TIMEOUT ({transitioning_duration:.1f}s) → CLEARED (paksa)")
                self._gate_lock_state = self.GATE_CLEARED
                return self._handle_gate_cleared(pass_label, step)

            if remaining_visible:
                # Bola tersisa masih ada di frame → pertahankan manuver condong adaptif
                lean_dir = self._lean_arrow(self._missing_color)
                label = f"GATE:TRANSITIONING({lean_dir}) steer={self._transition_steer:+.2f} | TRACKING_BUOY ({pass_label} pass)"
                return self._transition_steer, throttle, label
            else:
                # Bola terakhir juga hilang → gate CLEARED!
                self._gate_lock_state = self.GATE_CLEARED
                print("[GATE] TRANSITIONING → CLEARED (bola terakhir hilang)")
                return self._handle_gate_cleared(pass_label, step)

        # Fallback safety
        return 0.0, 0.0, f"GATE:UNKNOWN | TRACKING_BUOY ({pass_label} pass)"

    def _handle_gate_cleared(self, pass_label: str, step: Dict) -> Tuple[float, float, str]:
        """
        Dipanggil saat gate dinyatakan CLEARED.
        Increment pass count, reset state machine, dan kembali ke SEARCHING.
        """
        self._buoy_pass_count += 1
        target_pass_count = self._safe_int(step.get("pass_count"), 0)
        new_pass_label = f"{self._buoy_pass_count}/{target_pass_count}" if target_pass_count > 0 else str(self._buoy_pass_count)

        print(f"[GATE] 🏁 Gate CLEARED! Pass count: {self._buoy_pass_count}")
        self._broadcast_status()
        self._reset_gate_state_machine()   # kembali ke SEARCHING untuk gerbang berikutnya
        print(f"[GATE] CLEARED → SEARCHING (siap mengincar gerbang berikutnya)")

        label = f"GATE:CLEARED ✅ | TRACKING_BUOY ({new_pass_label} pass)"
        # Hentikan throttle sejenak agar tidak menabrak gate berikutnya
        return 0.0, 0.0, label

    def _handle_goto_gps(self, step, frame, gate_x, detected_balls=None):
        """Handle GOTO_GPS step."""
        target_lat = self._safe_float(step.get("lat"), 0.0)
        target_lon = self._safe_float(step.get("lon"), 0.0)

        now = time.time()
        telemetry = self.asv.get_telemetry()

        # Throttle pengiriman command goto_target agar tidak flooding MAVLink (setiap 1.5 detik)
        if telemetry.is_armed and (now - self._last_goto_time >= 1.5):
            self.asv.goto(target_lat, target_lon)
            self._last_goto_time = now

        # Cek apakah sudah sampai (radius acceptance) jika ada sinyal GPS valid
        if telemetry.lat != 0 and telemetry.lon != 0:
            dist = self._haversine(telemetry.lat, telemetry.lon, target_lat, target_lon)
            if dist <= self.ARRIVAL_RADIUS_M:
                print(f"[MissionEngine] ✅ GOTO step selesai! Tiba di {step.get('name','?')}")
                self._advance_step()
                return self.update_frame(frame, gate_x, detected_balls)

        return 0.0, 0.0, "GOTO_GPS"

    def _handle_take_image(self, step, frame, gate_x, detected_balls=None):
        """
        Handle TAKE_IMAGE step: kapal berhenti selama `duration_sec`, dan SEKALI
        selama itu memotret satu frame ber-geo-tag.

        Sebelumnya step ini sama sekali tidak menyimpan gambar apa pun — hanya diam
        lalu lanjut — sehingga tidak ada berkas yang bisa diberi geo-tag maupun
        dinilai.
        """
        duration = self._safe_float(step.get("duration_sec"), 3.0)
        elapsed = time.time() - self._step_start_time

        # Minta foto sekali per kunjungan ke step ini (identitas = _step_start_time).
        if self._capture_requested_at != self._step_start_time:
            self._capture_requested_at = self._step_start_time
            self._capture_pending = True
            self._capture_label = str(step.get("name") or f"step{step.get('id', '')}")
            print(f"[MissionEngine] 📸 TAKE_IMAGE '{self._capture_label}' — "
                  f"menunggu frame kamera bersih untuk difoto...")

        if elapsed >= duration:
            if self._capture_pending:
                # Durasi habis tapi frame bersih tidak pernah datang (mis. kamera mati).
                # Jangan menggantung permintaan foto ke step berikutnya.
                self._capture_pending = False
                print("[MissionEngine] ⚠️ TAKE_IMAGE selesai TANPA foto tersimpan "
                      "(tidak ada frame kamera).")
            print(f"[MissionEngine] ✅ TAKE_IMAGE selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x, detected_balls)

        return 0.0, 0.0, "TAKE_IMAGE"

    # ── API foto misi untuk main.py ──────────────────────────────────────────
    CAPTURE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "captures")

    @property
    def capture_pending(self) -> bool:
        """True kalau step TAKE_IMAGE sedang menunggu satu frame kamera untuk difoto."""
        return self._capture_pending

    def capture_now(self, frame) -> Optional[str]:
        """
        Simpan satu foto ber-geo-tag dari `frame`.

        WAJIB dipanggil dengan frame yang BELUM dianotasi (lihat _capture_pending).
        Dipanggil main.py di awal siklus frame, sebelum tracker menggambari frame.

        Return path gambar, atau None kalau gagal. Kegagalan tidak pernah dilempar
        ke pemanggil: satu foto yang gagal tidak boleh menjatuhkan misi yang berjalan.
        """
        if not self._capture_pending:
            return None
        self._capture_pending = False   # sekali percobaan per step, apa pun hasilnya
        telemetry = self.asv.get_telemetry_dict() if self.asv else {}
        return save_geotagged_image(frame, telemetry, self.CAPTURE_DIR,
                                    label=self._capture_label)

    # ------------------------------------------------------------------ #
    #  PHOTO_BOX — misi memotret box biru & box hijau                     #
    # ------------------------------------------------------------------ #

    @property
    def tracking_buoy_completed(self) -> bool:
        """
        True kalau salah satu step buoy (TRACKING_BUOY / SEQUENTIAL_BUOY /
        BUOY_CHASE) sudah SELESAI dalam run misi ini.

        Ditetapkan di _advance_step() — satu tempat yang dilewati SEMUA jalur
        penyelesaian step, termasuk yang selesai karena timeout atau karena buoy
        habis dari frame. Mengandalkan tiap handler menyetel flag-nya sendiri akan
        melewatkan jalur-jalur itu. Direset bersama state misi lain di
        load_mission(), start_mission(), dan reset_mission().
        """
        return self._tracking_buoy_completed

    def photo_mission(self, step: Dict, detected_boxes: Optional[Dict] = None
                      ) -> Tuple[float, float, str]:
        """
        Jalankan misi memotret box biru & box hijau.

        SATU KAMERA. Box biru konsepnya target bawah air dan box hijau target atas
        air, tapi di arena box biru masih menyembul di permukaan — jadi keduanya
        dicari lewat kamera permukaan yang sama yang dipakai tracking buoy. Method
        ini tidak pernah membuka kamera: frame-nya sudah mengalir dari VideoStreamer
        lewat main.py, dan foto bersihnya diambil capture_now(). Tidak ada
        inisialisasi kamera underwater di mana pun di jalur ini.

        SYARAT SEKUENSI: misi ini DILARANG berjalan sebelum step buoy selesai.
        Penjaganya ada di awal method — lihat tracking_buoy_completed.

        Untuk tiap target (default: biru lalu hijau) kapal melewati lima fase:

            SEARCH → ALIGN → APPROACH → SETTLE → SHOOT → target berikutnya

        Selesai (semua target sudah dicoba) → _advance_step().

        :param step: dict step misi. Field opsional, semuanya di-parse aman:
            target                (str)   "both" | "blue" | "green"  — urutan pemotretan
            throttle              (float) kecepatan meluncur mendekati box
            search_throttle       (float) kecepatan saat menyapu mencari box
            search_steer          (float) arah & kuat sapuan, negatif = kiri
            align_threshold_px    (float) toleransi pemusatan
            min_area_px2_blue     (float) ambang "cukup dekat" untuk box biru
            min_area_px2_green    (float) ambang "cukup dekat" untuk box hijau
            settle_sec            (float) lama diam sebelum shutter
            search_timeout_sec    (float) batas mencari satu box sebelum menyerah
        :param detected_boxes: {"blue_box": [...], "green_box": [...]} dari
            tracker.process_frame(). Tuple per deteksi: (cx, cy, x1, y1, x2, y2).
        :return: (steer_norm, thr_norm, label) — sama seperti handler step lain.
        """
        detected_boxes = detected_boxes or {}
        sekarang = time.time()

        # ── 1. GERBANG SEKUENSI ────────────────────────────────────────────
        # Kapal DITAHAN, bukan dibiarkan memotret. Kalau step ini sampai berjalan
        # duluan, urutan pipeline-nya salah dan posisi kapal tidak bisa ditebak.
        #
        # Ditahan LALU dilewati, bukan langsung dilewati atau menggantung selamanya:
        # menggantung mengunci misi sampai FINISH tidak pernah tercapai, sedangkan
        # langsung melewati membuat kesalahan urutan lewat tanpa sempat terlihat
        # operator. Menahan sebentar memberi jendela agar peringatannya terbaca di
        # base station, lalu misi tetap bisa jalan terus.
        if not self._tracking_buoy_completed:
            if self._photo_blocked_since is None:
                self._photo_blocked_since = sekarang
                print("[MissionEngine] ⛔ PHOTO_BOX DITOLAK — misi tracking buoy belum "
                      "selesai. Kapal ditahan; periksa urutan step di pipeline misi.")
            tertahan = sekarang - self._photo_blocked_since
            batas = self._safe_float(step.get("blocked_hold_sec"), self.PHOTO_BLOCKED_HOLD_SEC)
            if tertahan >= batas:
                print(f"[MissionEngine] ⏭️ PHOTO_BOX DILEWATI setelah ditahan "
                      f"{tertahan:.0f}s — syarat sekuensi tidak pernah terpenuhi.")
                self._advance_step()
                return 0.0, 0.0, "PHOTO_BOX | DILEWATI"
            if self.asv and self.asv.is_connected():
                self.asv.stop_movement(silent=True)
            return 0.0, 0.0, f"PHOTO_BOX | DIBLOKIR {tertahan:.0f}s"

        # ── 2. Target berikutnya ───────────────────────────────────────────
        target = self._next_photo_target(step)
        if target is None:
            jumlah = len(self._photo_done)
            print(f"[MissionEngine] ✅ PHOTO_BOX selesai — {jumlah} target diproses.")
            self._advance_step()
            return 0.0, 0.0, "PHOTO_BOX | SELESAI"

        if self._photo_target != target:
            self._photo_target = target
            self._set_photo_phase(self.PHOTO_SEARCH)
            print(f"[MissionEngine] 📷 PHOTO_BOX — mencari {ROLE_LABELS[target]}...")

        # ── 3. Kandidat terbesar = paling dekat ke kamera ──────────────────
        kandidat = (detected_boxes.get(target) or [])
        box = kandidat[0] if kandidat else None
        if box is not None:
            self._photo_last_seen_at = sekarang

        label_target = ROLE_LABELS[target]

        # ── 4. SHOOT: menunggu frame bersih dari main.py ───────────────────
        # Ditangani lebih dulu supaya hilangnya deteksi sesaat tidak membatalkan
        # foto yang shutter-nya sudah diminta.
        if self._photo_phase == self.PHOTO_SHOOT:
            return self._photo_wait_shutter(target, label_target, sekarang)

        # ── 5. Deteksi hilang ──────────────────────────────────────────────
        if box is None:
            hilang = sekarang - self._photo_last_seen_at
            if (self._photo_phase in (self.PHOTO_ALIGN, self.PHOTO_APPROACH)
                    and hilang < self.PHOTO_LOST_GRACE_SEC):
                # Kedip deteksi YOLO — pertahankan kemudi terakhir sebentar.
                thr = self._safe_float(step.get("throttle"), self.PHOTO_APPROACH_THROTTLE)
                return self._photo_last_steer, thr, f"PHOTO_BOX | {label_target} sesaat hilang"
            return self._photo_search(step, target, label_target, sekarang)

        # ── 6. Terlihat: ALIGN → APPROACH → SETTLE ────────────────────────
        cx, _cy, x1, y1, x2, y2 = box
        luas = float((x2 - x1) * (y2 - y1))
        error_px = float(cx - self.camera_width / 2.0)

        toleransi = self._px_dari_step(step, "align_threshold_px",
                                       self.PHOTO_ALIGN_THRESHOLD_PX)
        luas_minimum = self._photo_min_area(step, target)

        # Steer proporsional sederhana: +1.0 saat box di tepi KANAN frame.
        # Tanda mengikuti konvensi yang sama dengan seluruh engine ini
        # (steer positif = kapal belok kanan).
        steer = (self.PHOTO_STEER_KP * error_px) / max(1.0, self.camera_width / 2.0)
        steer = max(-self.PHOTO_MAX_STEER, min(self.PHOTO_MAX_STEER, steer))
        self._photo_last_steer = steer

        if abs(error_px) > toleransi:
            self._set_photo_phase(self.PHOTO_ALIGN)
            # Throttle kecil saat memusatkan: kapal tetap punya laju agar kemudinya
            # menggigit (kapal tanpa laju tidak berbelok), tapi tidak sampai melewati
            # box sebelum lurus.
            thr = self._safe_float(step.get("search_throttle"), self.PHOTO_SEARCH_THROTTLE)
            return steer, thr, f"PHOTO_BOX | ALIGN {label_target} err={error_px:+.0f}px"

        if luas < luas_minimum:
            self._set_photo_phase(self.PHOTO_APPROACH)
            thr = self._safe_float(step.get("throttle"), self.PHOTO_APPROACH_THROTTLE)
            return steer, thr, (f"PHOTO_BOX | APPROACH {label_target} "
                                f"{luas / max(1.0, luas_minimum) * 100:.0f}%")

        # Cukup dekat & lurus → berhenti dan tunggu kapal diam.
        if self._photo_phase != self.PHOTO_SETTLE:
            self._set_photo_phase(self.PHOTO_SETTLE)
            print(f"[MissionEngine] 🛑 {label_target} sudah dekat & lurus — "
                  f"menunggu kapal diam sebelum memotret...")
        if self.asv and self.asv.is_connected():
            self.asv.stop_movement(silent=True)

        diam = sekarang - self._photo_phase_since
        tunggu = self._safe_float(step.get("settle_sec"), self.PHOTO_SETTLE_SEC)
        if diam < tunggu:
            return 0.0, 0.0, f"PHOTO_BOX | SETTLE {label_target} {diam:.1f}/{tunggu:.1f}s"

        # Minta shutter. Foto diambil main.py dari frame BERSIH (sebelum tracker
        # menggambari bounding box) lewat capture_now() — mekanisme yang sama dengan
        # TAKE_IMAGE, supaya yang dinilai juri adalah pemandangan asli.
        self._capture_requested_at = sekarang
        self._capture_pending = True
        self._capture_label = target
        self._set_photo_phase(self.PHOTO_SHOOT)
        print(f"[MissionEngine] 📸 Memotret {label_target}...")
        return 0.0, 0.0, f"PHOTO_BOX | SHOOT {label_target}"

    def _handle_photo_box(self, step, frame, gate_x, detected_balls, detected_boxes):
        """
        Adapter dispatch update_frame → photo_mission().

        Ada di sini, bukan di dalam photo_mission(), supaya photo_mission() tetap
        bisa dipanggil sendiri dengan argumen seadanya (step + deteksi box) — mis.
        dari uji atau alat bantu — tanpa ikut membawa frame & gate_x yang tidak
        dipakainya.

        Kalau photo_mission() menyelesaikan step ini, step BERIKUTNYA langsung
        dijalankan di frame yang sama, persis seperti handler step lain. Tanpa
        rekursi ini kapal mendapat satu frame berisi (0, 0) di sela pergantian step
        — jeda yang tidak berbahaya tapi membuat perilakunya beda sendiri dari
        seluruh engine.
        """
        idx_sebelum = self._current_step_idx
        hasil = self.photo_mission(step, detected_boxes)
        if self._current_step_idx != idx_sebelum:
            return self.update_frame(frame, gate_x, detected_balls)
        return hasil

    def _photo_wait_shutter(self, target: str, label_target: str, sekarang: float
                            ) -> Tuple[float, float, str]:
        """Tahan posisi sampai capture_now() mengambil fotonya, atau kamera menyerah."""
        if self.asv and self.asv.is_connected():
            self.asv.stop_movement(silent=True)

        if not self._capture_pending:
            self._photo_done.append(target)
            print(f"[MissionEngine] ✅ Foto {label_target} tersimpan.")
            self._photo_target = None
            return 0.0, 0.0, f"PHOTO_BOX | {label_target} OK"

        if sekarang - self._photo_phase_since >= self.PHOTO_SHOOT_TIMEOUT_SEC:
            # Frame bersih tidak pernah datang (mis. kamera mati). Jangan menggantungkan
            # permintaan foto ke step berikutnya — pola yang sama dengan TAKE_IMAGE.
            self._capture_pending = False
            self._photo_done.append(target)
            self._photo_target = None
            print(f"[MissionEngine] ⚠️ Foto {label_target} GAGAL — tidak ada frame kamera.")
            return 0.0, 0.0, f"PHOTO_BOX | {label_target} GAGAL"

        return 0.0, 0.0, f"PHOTO_BOX | SHOOT {label_target}"

    def _photo_search(self, step: Dict, target: str, label_target: str, sekarang: float
                      ) -> Tuple[float, float, str]:
        """Menyapu mencari box yang belum terlihat, sampai batas waktu."""
        if self._photo_phase != self.PHOTO_SEARCH:
            self._set_photo_phase(self.PHOTO_SEARCH)

        dicari = sekarang - self._photo_phase_since
        batas = self._safe_float(step.get("search_timeout_sec"), self.PHOTO_SEARCH_TIMEOUT_SEC)
        if dicari >= batas:
            print(f"[MissionEngine] ⏭️ {label_target} tidak ditemukan dalam {batas:.0f}s — "
                  f"dilewati, lanjut ke target berikutnya.")
            self._photo_done.append(target)
            self._photo_target = None
            return 0.0, 0.0, f"PHOTO_BOX | {label_target} TIDAK KETEMU"

        steer = self._safe_float(step.get("search_steer"), self.PHOTO_SEARCH_STEER)
        steer = max(-1.0, min(1.0, steer))
        thr = self._safe_float(step.get("search_throttle"), self.PHOTO_SEARCH_THROTTLE)
        self._photo_last_steer = steer
        return steer, thr, f"PHOTO_BOX | SEARCH {label_target} {dicari:.0f}/{batas:.0f}s"

    def _photo_urutan_target(self, step: Dict) -> List[str]:
        """
        Urutan box yang akan difoto, dari field `target`.

        Dipisah jadi fungsi sendiri supaya dropdown di panel misi bisa diuji
        terhadap keputusan yang SESUNGGUHNYA (lihat tools/uji_opsi_panel.py).
        Menuliskan ulang aturannya di berkas uji cuma menguji tiruan yang bisa
        menyimpang diam-diam dari yang dijalankan kapal.
        """
        pilihan = self._target_box_normal(step.get("target"), "both")
        if pilihan == "blue":
            return [ROLE_BLUE_BOX]
        if pilihan == "green":
            return [ROLE_GREEN_BOX]
        # Biru lebih dulu: bagiannya yang terlihat dari permukaan paling kecil,
        # jadi paling butuh kapal mendekat — dikerjakan selagi waktu step masih panjang.
        return [ROLE_BLUE_BOX, ROLE_GREEN_BOX]

    def _next_photo_target(self, step: Dict) -> Optional[str]:
        """Peran box berikutnya yang belum diproses, atau None kalau semua selesai."""
        for peran in self._photo_urutan_target(step):
            if peran not in self._photo_done:
                return peran
        return None

    def _px_dari_step(self, step: Dict, key: str, default_terskala: float) -> float:
        """
        Baca JARAK piksel dari field step, diskalakan dari resolusi referensi.

        Nilai di panel misi ditulis dalam satuan REFERENSI (1920x1080) — defaultnya
        memang disalin dari konstanta class di file ini. Jadi nilai itu harus melewati
        penskalaan yang sama seperti konstantanya, bukan dipakai mentah. `default_
        terskala` sudah diskalakan oleh _apply_resolution_scaling(), jadi dipakai apa
        adanya saat field-nya kosong.
        """
        nilai = self._safe_float(step.get(key), -1.0)
        if nilai <= 0:
            return default_terskala
        return nilai * self._px_scale

    def _area_dari_step(self, step: Dict, key: str, default_terskala: float) -> float:
        """Versi AREA (piksel²) dari _px_dari_step — skala lebar x tinggi, bukan lebar saja."""
        nilai = self._safe_float(step.get(key), -1.0)
        if nilai <= 0:
            return default_terskala
        return nilai * self._area_scale

    def _photo_min_area(self, step: Dict, target: str) -> float:
        """Ambang luas "cukup dekat" untuk target ini — beda per warna, lihat konstanta."""
        if target == ROLE_BLUE_BOX:
            return self._area_dari_step(step, "min_area_px2_blue",
                                        self.PHOTO_MIN_AREA_PX2_BLUE)
        return self._area_dari_step(step, "min_area_px2_green",
                                    self.PHOTO_MIN_AREA_PX2_GREEN)

    def _set_photo_phase(self, fase: str):
        """Pindah fase sambil mencatat waktunya (dipakai semua timeout di step ini)."""
        if self._photo_phase != fase:
            self._photo_phase = fase
            self._photo_phase_since = time.time()

    def _reset_photo_state(self):
        """Kembalikan state PHOTO_BOX ke awal. Dipanggil saat step ini baru dimulai."""
        self._photo_phase = self.PHOTO_SEARCH
        self._photo_phase_since = time.time()
        self._photo_target = None
        self._photo_done = []
        self._photo_last_seen_at = 0.0
        self._photo_last_steer = 0.0
        self._photo_blocked_since = None

    # ------------------------------------------------------------------ #
    #  BOX_CHANNEL — susuri celah antar box, berhenti & foto tiap box     #
    # ------------------------------------------------------------------ #

    def box_channel(self, step: Dict, detected_boxes: Optional[Dict] = None
                    ) -> Tuple[float, float, str]:
        """
        Lewati celah di antara box biru & hijau sambil memotret keduanya.

        BEDANYA DENGAN PHOTO_BOX: step itu membidik KE ARAH box lalu maju ke sana.
        Di lintasan ini kapal justru harus lewat DI ANTARA keduanya — membidik satu
        box dan memburunya akan menarik kapal ke tepi lintasan, bukan menyusurinya.

        KENAPA TIDAK MEMAKAI MATEMATIKA GERBANG: box tidak berdampingan seperti bola,
        melainkan BERSELANG di sepanjang lintasan (biru lebih dulu di kanan, hijau
        menyusul di kiri). Titik tengah piksel dua objek yang jaraknya jauh berbeda
        tidak menunjuk tengah celah yang sebenarnya, dan keduanya sering tidak
        terlihat bersamaan.

        Yang dipakai: KONVENSI SISI (vision/gate_convention.py). Box biru menandai
        tepi kanan, hijau menandai tepi kiri — jadi SATU box yang terlihat sudah
        cukup untuk tahu di sebelah mana celahnya. Arah selalu diambil dari box
        TERDEKAT (bbox terbesar), karena perspektifnya paling bisa dipercaya.

        Urutan per box: TRANSIT → AIM → SETTLE → SHOOT → lanjut box berikutnya.
        Kapal berhenti dan memusatkan box lebih dulu sebelum menjepret, lalu kembali
        menyusuri celah.

        :param step: field opsional (semuanya di-parse aman):
            throttle              laju menyusuri celah
            aim_throttle          laju saat membidik — lihat BOXCH_AIM_THROTTLE
            channel_offset_px     jarak titik lewat dari satu box
            align_threshold_px    toleransi pemusatan sebelum menjepret
            min_area_px2_blue     ambang "cukup dekat" box biru
            min_area_px2_green    ambang "cukup dekat" box hijau
            settle_sec            lama diam sebelum shutter
            aim_timeout_sec       batas membidik sebelum menjepret seadanya
            blind_stop_sec        lama maju buta sebelum berhenti
            no_detection_finish_sec  lama tanpa box sebelum step diselesaikan
        :param detected_boxes: {"blue_box": [...], "green_box": [...]} dari tracker.
        :return: (steer_norm, thr_norm, label)
        """
        detected_boxes = detected_boxes or {}
        sekarang = time.time()

        terbesar = self._boxch_terbesar(detected_boxes)
        if terbesar is not None:
            self._boxch_last_seen_at = sekarang
            self._boxch_blind_since = None

        # ── SHOOT: menunggu frame bersih dari main.py ──────────────────────
        # Didahulukan supaya deteksi yang berkedip tidak membatalkan foto yang
        # shutter-nya sudah diminta.
        if self._boxch_phase == self.BOX_SHOOT:
            return self._boxch_tunggu_shutter(step, sekarang)

        # ── EVADE: membanting menjauh dari box yang baru difoto ────────────
        # Sengaja didahulukan juga: begitu kapal berbelok, box-nya keluar frame,
        # dan kalau menghindar bergantung pada box yang masih terlihat, manuvernya
        # akan terpotong tepat saat paling dibutuhkan.
        if self._boxch_phase == self.BOX_EVADE:
            lama = sekarang - self._boxch_phase_since
            durasi = self._safe_float(step.get("evade_sec"), self.BOXCH_EVADE_SEC)
            if lama < durasi:
                thr = self._safe_float(step.get("throttle"), self.BOXCH_TRANSIT_THROTTLE)
                return self._boxch_evade_steer, thr, \
                    f"BOX_CHANNEL | EVADE {lama:.1f}/{durasi:.1f}s"
            self._boxch_set_phase(self.BOX_TRANSIT)

        # ── Tidak ada box terlihat sama sekali ─────────────────────────────
        if terbesar is None:
            return self._boxch_buta(step, sekarang)

        peran, box = terbesar
        cx, _cy, x1, y1, x2, y2 = box
        luas = float((x2 - x1) * (y2 - y1))
        setengah = self.camera_width / 2.0

        # ── Arah menyusuri celah, dari box TERDEKAT ────────────────────────
        offset = self._boxch_offset_px(step, box)
        titik_lewat = virtual_gate_center_x(cx, peran, offset)
        steer_alur = max(-1.0, min(1.0, (titik_lewat - setengah) / max(1.0, setengah)))

        # ── Adakah box yang siap dibidik? ──────────────────────────────────
        siap = self._boxch_target_siap(step, detected_boxes)

        if siap is None:
            # Belum ada yang cukup dekat — terus menyusuri celah.
            self._boxch_set_phase(self.BOX_TRANSIT)
            self._boxch_target = None
            self._boxch_last_steer = steer_alur
            thr = self._safe_float(step.get("throttle"), self.BOXCH_TRANSIT_THROTTLE)
            return steer_alur, thr, (f"BOX_CHANNEL | TRANSIT lewat {ROLE_LABELS[peran]} "
                                     f"steer={steer_alur:+.2f}")

        peran_target, box_target = siap
        if self._boxch_target != peran_target:
            self._boxch_target = peran_target
            self._boxch_set_phase(self.BOX_AIM)
            print(f"[MissionEngine] 📷 {ROLE_LABELS[peran_target]} sudah dekat — "
                  f"berhenti dan membidik...")

        tcx = box_target[0]
        error_px = float(tcx - setengah)
        toleransi = self._px_dari_step(step, "align_threshold_px",
                                       self.BOXCH_ALIGN_THRESHOLD_PX)
        steer_bidik = max(-self.PHOTO_MAX_STEER,
                          min(self.PHOTO_MAX_STEER,
                              (self.PHOTO_STEER_KP * error_px) / max(1.0, setengah)))
        self._boxch_last_steer = steer_bidik
        label_target = ROLE_LABELS[peran_target]

        bergerak = self._boxch_mode_bergerak(step)
        luas_target = float((box_target[4] - box_target[2]) * (box_target[5] - box_target[3]))

        # ── AIM: putar sampai box di tengah ────────────────────────────────
        if self._boxch_phase == self.BOX_AIM:
            lama_bidik = sekarang - self._boxch_phase_since
            batas = self._safe_float(step.get("aim_timeout_sec"), self.BOXCH_AIM_TIMEOUT_SEC)
            batas_luas = (self._boxch_min_area(step, peran_target)
                          * self.BOXCH_FORCE_SHOOT_AREA_RATIO)
            if bergerak and luas_target >= batas_luas:
                # Sudah terlalu dekat sementara masih melaju. Waktu bukan ukuran
                # yang tepat di sini — jaraklah yang menentukan bahaya.
                print(f"[MissionEngine] ⚠️ {label_target} sudah terlalu dekat "
                      f"(belum terpusat) — jepret sekarang lalu menghindar.")
                self._boxch_set_phase(self.BOX_SETTLE)
            elif abs(error_px) <= toleransi:
                self._boxch_set_phase(self.BOX_SETTLE)
            elif lama_bidik >= batas:
                # Menyerah memusatkan. Menjepret dengan framing seadanya jauh lebih
                # baik daripada kapal terus merayap mengejar pemusatan sempurna —
                # itu yang berujung menyenggol box.
                print(f"[MissionEngine] ⏱️ {label_target} tidak terpusat dalam "
                      f"{batas:.0f}s — difoto apa adanya (err={error_px:+.0f}px).")
                self._boxch_set_phase(self.BOX_SETTLE)
            else:
                # Mode moving TIDAK melambat: laju jelajah dipertahankan supaya
                # kapal tidak kehilangan momentum sebelum manuver menghindar.
                thr = (self._safe_float(step.get("throttle"), self.BOXCH_TRANSIT_THROTTLE)
                       if bergerak
                       else self._safe_float(step.get("aim_throttle"), self.BOXCH_AIM_THROTTLE))
                mode_lbl = "jalan" if bergerak else "diam"
                return steer_bidik, thr, (f"BOX_CHANNEL | AIM {label_target} ({mode_lbl}) "
                                          f"err={error_px:+.0f}px {lama_bidik:.1f}/{batas:.0f}s")

        # ── SETTLE: berhenti, tunggu kapal diam ────────────────────────────
        # Mode moving MELEWATI fase ini seluruhnya — tidak berhenti, tidak menunggu.
        # Itu memang inti perbedaannya: foto sedikit kurang tajam, ditukar dengan
        # lintasan yang tidak terputus.
        if self._boxch_phase == self.BOX_SETTLE:
            # Berhenti & menunggu HANYA di mode stop. Mode moving lewat begitu saja
            # ke shutter — itu memang inti perbedaan keduanya.
            if not bergerak:
                if self.asv and self.asv.is_connected():
                    self.asv.stop_movement(silent=True)
                diam = sekarang - self._boxch_phase_since
                tunggu = self._safe_float(step.get("settle_sec"), self.BOXCH_SETTLE_SEC)
                if diam < tunggu:
                    return 0.0, 0.0, (f"BOX_CHANNEL | SETTLE {label_target} "
                                      f"{diam:.1f}/{tunggu:.1f}s")

            # Minta shutter. main.py memotret dari frame BERSIH (sebelum tracker
            # menggambari bounding box) — mekanisme yang sama dengan TAKE_IMAGE.
            self._capture_requested_at = sekarang
            self._capture_pending = True
            self._capture_label = peran_target
            # Arah menghindar disiapkan SEKARANG, selagi kita masih tahu box mana
            # yang dibidik: begitu kapal membanting, box-nya keluar frame.
            self._boxch_evade_steer = channel_sign(peran_target) * self._safe_float(
                step.get("evade_steer"), self.BOXCH_EVADE_STEER)
            self._boxch_set_phase(self.BOX_SHOOT)
            print(f"[MissionEngine] 📸 Memotret {label_target}"
                  f"{' (sambil jalan)' if bergerak else ''}...")
            thr = (self._safe_float(step.get("throttle"), self.BOXCH_TRANSIT_THROTTLE)
                   if bergerak else 0.0)
            return (steer_bidik if bergerak else 0.0), thr, \
                f"BOX_CHANNEL | SHOOT {label_target}"

        return steer_alur, self._safe_float(step.get("throttle"),
                                            self.BOXCH_TRANSIT_THROTTLE), \
            f"BOX_CHANNEL | TRANSIT {label_target}"

    def _handle_box_channel(self, step, frame, gate_x, detected_balls, detected_boxes):
        """Adapter dispatch update_frame → box_channel(); rekursi saat step selesai."""
        idx_sebelum = self._current_step_idx
        hasil = self.box_channel(step, detected_boxes)
        if self._current_step_idx != idx_sebelum:
            return self.update_frame(frame, gate_x, detected_balls)
        return hasil

    def _boxch_offset_px(self, step: Dict, box) -> float:
        """
        Jarak (piksel) titik lewat dari box, untuk FRAME INI.

        Kalau lebar box sebenarnya diketahui (field `box_width_m`), offset dihitung
        dari lebar bbox-nya sehingga jaraknya tetap sekian METER berapa pun jarak
        kapal ke box — lihat catatan di BOXCH_CHANNEL_OFFSET_M.

        Hasil perhitungan ini TIDAK diskalakan lagi ke resolusi: ia sudah berasal
        dari piksel frame yang sedang berjalan, jadi menskalakannya sekali lagi
        justru salah.
        """
        lebar_box_m = self._safe_float(step.get("box_width_m"), self.BOXCH_BOX_WIDTH_M)
        offset_m = self._safe_float(step.get("channel_offset_m"), self.BOXCH_CHANNEL_OFFSET_M)
        lebar_bbox_px = float(box[4] - box[2])

        if lebar_box_m > 0 and offset_m > 0 and lebar_bbox_px > 0:
            return (lebar_bbox_px / lebar_box_m) * offset_m

        # Belum diukur: pakai offset piksel tetap (diskalakan dari resolusi referensi).
        return self._px_dari_step(step, "channel_offset_px", self.BOXCH_CHANNEL_OFFSET_PX)

    def _boxch_terbesar(self, detected_boxes: Dict):
        """(peran, box) dengan bbox TERBESAR = paling dekat, atau None."""
        terbaik = None
        luas_terbaik = 0.0
        for peran in (ROLE_BLUE_BOX, ROLE_GREEN_BOX):
            for b in (detected_boxes.get(peran) or []):
                luas = (b[4] - b[2]) * (b[5] - b[3])
                if luas > luas_terbaik:
                    luas_terbaik = luas
                    terbaik = (peran, b)
        return terbaik

    def _boxch_target_siap(self, step: Dict, detected_boxes: Dict):
        """Box yang BELUM difoto dan sudah cukup dekat untuk dibidik, atau None."""
        for peran in (ROLE_BLUE_BOX, ROLE_GREEN_BOX):
            if peran in self._boxch_done:
                continue
            kandidat = (detected_boxes.get(peran) or [])
            if not kandidat:
                continue
            b = kandidat[0]
            luas = (b[4] - b[2]) * (b[5] - b[3])
            if luas >= self._boxch_min_area(step, peran):
                return peran, b
        return None

    def _boxch_min_area(self, step: Dict, peran: str) -> float:
        if peran == ROLE_BLUE_BOX:
            return self._area_dari_step(step, "min_area_px2_blue",
                                        self.BOXCH_MIN_AREA_PX2_BLUE)
        return self._area_dari_step(step, "min_area_px2_green",
                                    self.BOXCH_MIN_AREA_PX2_GREEN)

    def _boxch_mode_bergerak(self, step: Dict) -> bool:
        """
        True kalau step ini memotret SAMBIL JALAN.

        Dua mode sengaja dijadikan satu field, bukan dua tipe step: di danau,
        membandingkan keduanya jadi soal mengganti satu nilai lalu menjalankan ulang
        — bukan menyusun pipeline baru dengan belasan field yang harus disamakan
        satu per satu.
        """
        mode = str(step.get("mode") or "stop").strip().lower()
        return mode in ("moving", "jalan", "bergerak", "move")

    def _boxch_tunggu_shutter(self, step: Dict, sekarang: float) -> Tuple[float, float, str]:
        """Tahan posisi sampai capture_now() mengambil fotonya, atau kamera menyerah."""
        bergerak = self._boxch_mode_bergerak(step)
        if not bergerak and self.asv and self.asv.is_connected():
            self.asv.stop_movement(silent=True)
        peran = self._boxch_target
        label = ROLE_LABELS.get(peran, "box")

        if not self._capture_pending:
            if peran and peran not in self._boxch_done:
                self._boxch_done.append(peran)
            self._boxch_target = None
            if bergerak:
                # Kapal sedang mengarah TEPAT ke box yang baru difoto — membanting
                # menjauh dulu sebelum kembali menyusuri celah.
                self._boxch_set_phase(self.BOX_EVADE)
                print(f"[MissionEngine] ✅ Foto {label} tersimpan — menghindar "
                      f"({'kiri' if self._boxch_evade_steer < 0 else 'kanan'}) lalu lanjut.")
                thr = self._safe_float(step.get("throttle"), self.BOXCH_TRANSIT_THROTTLE)
                return self._boxch_evade_steer, thr, f"BOX_CHANNEL | EVADE {label}"
            print(f"[MissionEngine] ✅ Foto {label} tersimpan — lanjut menyusuri celah.")
            self._boxch_set_phase(self.BOX_TRANSIT)
            return 0.0, 0.0, f"BOX_CHANNEL | {label} OK"

        if sekarang - self._boxch_phase_since >= self.BOXCH_SHOOT_TIMEOUT_SEC:
            # Frame bersih tidak pernah datang (mis. kamera mati). Jangan
            # menggantungkan permintaan foto ke step berikutnya.
            self._capture_pending = False
            if peran and peran not in self._boxch_done:
                self._boxch_done.append(peran)
            self._boxch_target = None
            # Tetap menghindar walau fotonya gagal: kapal sudah terlanjur mengarah
            # ke box, dan kegagalan kamera bukan alasan untuk menabraknya.
            self._boxch_set_phase(self.BOX_EVADE if bergerak else self.BOX_TRANSIT)
            print(f"[MissionEngine] ⚠️ Foto {label} GAGAL — tidak ada frame kamera.")
            return 0.0, 0.0, f"BOX_CHANNEL | {label} GAGAL"

        return 0.0, 0.0, f"BOX_CHANNEL | SHOOT {label}"

    def _boxch_buta(self, step: Dict, sekarang: float) -> Tuple[float, float, str]:
        """Tidak ada box terlihat: maju sebentar, lalu berhenti, lalu selesaikan step."""
        if self._boxch_blind_since is None:
            self._boxch_blind_since = sekarang
        buta = sekarang - self._boxch_blind_since

        selesai_sec = self._safe_float(step.get("no_detection_finish_sec"),
                                       self.BOXCH_NO_DETECTION_FINISH_SEC)
        if buta >= selesai_sec:
            print(f"[MissionEngine] ✅ BOX_CHANNEL selesai — {len(self._boxch_done)} box "
                  f"difoto, tidak ada box lagi selama {buta:.0f}s.")
            self._advance_step()
            return 0.0, 0.0, "BOX_CHANNEL | SELESAI"

        # Kedip deteksi sesaat: pertahankan kemudi terakhir supaya kapal tidak
        # langsung meluruskan haluan di tengah celah.
        if (sekarang - self._boxch_last_seen_at) < self.BOXCH_LOST_GRACE_SEC:
            thr = self._safe_float(step.get("throttle"), self.BOXCH_TRANSIT_THROTTLE)
            return self._boxch_last_steer, thr, "BOX_CHANNEL | box sesaat hilang"

        self._boxch_set_phase(self.BOX_TRANSIT)
        berhenti_sec = self._safe_float(step.get("blind_stop_sec"), self.BOXCH_BLIND_STOP_SEC)
        if buta >= berhenti_sec:
            # Berhenti, JANGAN maju buta terus — itu yang membuat kapal keluar arena.
            return 0.0, 0.0, f"BOX_CHANNEL | buta {buta:.0f}s, berhenti"
        thr = self._safe_float(step.get("throttle"), self.BOXCH_TRANSIT_THROTTLE)
        return 0.0, thr, f"BOX_CHANNEL | mencari box {buta:.0f}/{berhenti_sec:.0f}s"

    def _boxch_set_phase(self, fase: str):
        if self._boxch_phase != fase:
            self._boxch_phase = fase
            self._boxch_phase_since = time.time()

    def _reset_boxch_state(self):
        """Kembalikan state BOX_CHANNEL ke awal. Dipanggil saat step ini dimulai."""
        self._boxch_phase = self.BOX_TRANSIT
        self._boxch_phase_since = time.time()
        self._boxch_target = None
        self._boxch_done = []
        self._boxch_last_seen_at = 0.0
        self._boxch_last_steer = 0.0
        self._boxch_blind_since = None
        self._boxch_evade_steer = 0.0

    # ------------------------------------------------------------------ #
    #  BOX_APPROACH — Cari box → Dekati → Menghindar                      #
    # ------------------------------------------------------------------ #

    def box_approach(self, step: Dict, detected_boxes: Optional[Dict] = None
                     ) -> Tuple[float, float, str]:
        """
        Cari satu box, dekati sampai terpusat & cukup dekat, lalu menghindar.

        Tiga fase inti, berurutan dan tidak pernah mundur kecuali box hilang:

            SCAN ──► APPROACH ──► EVADE ──► step selesai

        Kalau field `photo` dinyalakan, satu fase disisipkan sebelum menghindar:

            SCAN ──► APPROACH ──► SHOOT ──► EVADE ──► step selesai

        Default-nya MATI. Step ini dibuat untuk mencari perilaku manuver yang benar,
        dan shutter mengubah waktu tempuh — menyalakannya diam-diam akan membuat
        angka yang sudah di-tuning tidak lagi berarti sama.

        BEDANYA DENGAN BOX_CHANNEL: step itu menyusuri celah di antara DUA box dan
        memotret keduanya. Step ini hanya mengurus SATU box dan tidak memotret sama
        sekali — semua parameternya terbuka untuk di-tuning, jadi cocok dipakai
        mencari perilaku yang benar di danau sebelum dipindahkan ke step yang lebih
        pintar. Untuk box kedua, pasang lagi step ini dengan target warna yang lain.

        URUTAN SETELAH BUOY: ditentukan oleh POSISI step di pipeline, bukan oleh
        gerbang tersembunyi di dalam sini. Taruh step ini setelah step buoy
        (TRACKING_BUOY / SEQUENTIAL_BUOY / BUOY_CHASE) dan urutannya otomatis benar.
        Sengaja tidak memakai gerbang seperti PHOTO_BOX: gerbang yang menahan diam
        pernah terbaca sebagai "kapal tidak jalan" tanpa petunjuk apa pun di layar.

        Field step yang bisa di-tuning (semua opsional, semua di-parse aman —
        kosong/salah ketik jatuh ke default, tidak pernah melempar exception):

          target                  "blue"/"biru" (default) atau "green"/"hijau"

          --- Fase SCAN ---
          scan_throttle           laju saat mencari                     (0..1)
          scan_steer              arah & kuat sapuan: NEGATIF = kiri,
                                  POSITIF = kanan, 0 = maju lurus       (-1..1)
          scan_timeout_sec        tidak ketemu selama ini → step selesai

          --- Fase APPROACH ---
          approach_throttle       laju saat mendekat                    (0..1)
          approach_steer_gain     sensitivitas pemusatan ke box
          max_steer               batas kemudi saat mendekat            (0..1)
          min_detect_area_px2     bbox di bawah ini bukan box (anti false positive)
          lost_grace_sec          box hilang sekejap → tahan kemudi terakhir

          --- Pemicu menghindar ---
          center_tolerance_px     "sudah di tengah" = simpangan <= ini
          target_area_px2         "sudah dekat" = luas bbox >= ini
          force_evade_area_ratio  pengaman tabrakan (lihat catatan di bawah)

          --- Foto (opsional, default MATI) ---
          photo                   "off" (default) | "stop" | "moving"
          photo_settle_sec        lama diam sebelum shutter, mode "stop" saja

          --- Fase EVADE ---
          evade_direction         "left"/"kiri", "right"/"kanan", atau "auto"
          evade_throttle          laju saat menghindar                  (0..1)
          evade_steer             kuat bantingan                        (0..1)
          evade_sec               lama manuver menghindar

          --- Pengaman ---
          max_duration_sec        batas keras seluruh step

        PENGAMAN TABRAKAN, kenapa ada: syarat menghindar adalah "di tengah DAN
        cukup dekat" — dua syarat yang harus terpenuhi BERSAMAAN. Kalau box tidak
        pernah benar-benar terpusat (toleransi kesempitan, arus menyamping, box
        miring), syarat itu tidak pernah terpenuhi sementara kapal terus mendekat.
        Tanpa penjaga, satu-satunya yang menghentikan kapal adalah box itu sendiri.
        Karena itu, begitu luas bbox melewati target x force_evade_area_ratio,
        kapal menghindar SEKARANG walau belum terpusat.

        :param step: dict step misi.
        :param detected_boxes: {"blue_box": [...], "green_box": [...]} dari tracker.
            Tuple per deteksi: (cx, cy, x1, y1, x2, y2).
        :return: (steer_norm, thr_norm, label) — sama seperti handler step lain.
        """
        detected_boxes = detected_boxes or {}
        sekarang = time.time()

        # ── Batas keras seluruh step ───────────────────────────────────────
        # Dicek paling awal supaya berlaku di fase mana pun, termasuk saat kapal
        # sedang mendekat dan box tidak kunjung membesar.
        batas_step = self._safe_float(step.get("max_duration_sec"), self.BAP_MAX_DURATION_SEC)
        if batas_step > 0 and self._step_start_time:
            umur = sekarang - self._step_start_time
            if umur >= batas_step:
                print(f"[MissionEngine] ⏱️ BOX_APPROACH dihentikan — batas {batas_step:.0f}s "
                      f"terlampaui di fase {self._bap_phase}.")
                # Permintaan shutter yang belum dilayani JANGAN diwariskan: step
                # berikutnya akan memotret pada momen yang sama sekali tidak diminta.
                if self._bap_shutter_diminta:
                    self._capture_pending = False
                self._advance_step()
                return 0.0, 0.0, "BOX_APPROACH | BATAS WAKTU"

        # ── EVADE didahulukan ──────────────────────────────────────────────
        # Begitu kapal membanting, box-nya keluar frame. Kalau manuver ini
        # bergantung pada box yang masih terlihat, ia akan terpotong tepat saat
        # paling dibutuhkan.
        if self._bap_phase == self.BAP_EVADE:
            return self._bap_menghindar(step, sekarang)

        # SHOOT juga didahulukan: shutter yang sudah diminta tidak boleh dibatalkan
        # hanya karena deteksi box berkedip satu frame.
        if self._bap_phase == self.BAP_SHOOT:
            return self._bap_memotret(step, sekarang)

        peran = self._bap_peran_target(step)
        min_deteksi = self._area_dari_step(step, "min_detect_area_px2",
                                           self.BAP_MIN_DETECT_AREA_PX2)
        box = self._bap_box_terdekat(detected_boxes, peran, min_deteksi)

        if box is None:
            return self._bap_mencari(step, sekarang)

        self._bap_last_seen_at = sekarang

        # ── APPROACH: pusatkan box sambil mendekat ─────────────────────────
        cx = float(box[0])
        luas = self._bbox_area(box)
        setengah = self.camera_width / 2.0
        error_px = cx - setengah

        gain = self._safe_float(step.get("approach_steer_gain"),
                                self.BAP_APPROACH_STEER_GAIN)
        batas_steer = min(1.0, abs(self._safe_float(step.get("max_steer"),
                                                    self.BAP_MAX_STEER)))
        steer = (gain * error_px) / max(1.0, setengah)
        steer = max(-batas_steer, min(batas_steer, steer))
        self._bap_last_steer = steer
        self._bap_set_phase(self.BAP_APPROACH)

        toleransi = self._px_dari_step(step, "center_tolerance_px",
                                       self.BAP_CENTER_TOLERANCE_PX)
        area_target = self._area_dari_step(step, "target_area_px2",
                                           self.BAP_TARGET_AREA_PX2)
        di_tengah = abs(error_px) <= toleransi
        cukup_dekat = luas >= area_target

        rasio = self._safe_float(step.get("force_evade_area_ratio"),
                                 self.BAP_FORCE_EVADE_AREA_RATIO)
        terlalu_dekat = rasio > 0 and luas >= (area_target * rasio)

        if di_tengah and cukup_dekat:
            return self._bap_mulai_menghindar(
                step, sekarang, peran,
                f"terpusat ({error_px:+.0f}px) & jarak target tercapai")

        if terlalu_dekat:
            # Pengaman tabrakan — lihat catatan di docstring.
            return self._bap_mulai_menghindar(
                step, sekarang, peran,
                f"PENGAMAN: terlalu dekat, belum terpusat ({error_px:+.0f}px)")

        thr = self._bap_throttle(step, "approach_throttle", self.BAP_APPROACH_THROTTLE)
        return steer, thr, (f"BOX_APPROACH | APPROACH {ROLE_LABELS[peran]} "
                            f"err={error_px:+.0f}px luas={luas/max(1.0, area_target):.0%}")

    def _handle_box_approach(self, step, frame, gate_x, detected_balls, detected_boxes):
        """Adapter dispatch update_frame → box_approach(); rekursi saat step selesai."""
        idx_sebelum = self._current_step_idx
        hasil = self.box_approach(step, detected_boxes)
        if self._current_step_idx != idx_sebelum:
            return self.update_frame(frame, gate_x, detected_balls)
        return hasil

    @staticmethod
    def _target_box_normal(nilai, default: str) -> str:
        """
        Ejaan apa pun untuk warna box → "blue" | "green" | nilai apa adanya.

        Satu tempat untuk daftar ejaannya. Sebelumnya daftar yang sama persis
        ditulis ulang di tiga handler (PHOTO_BOX, STEER_UNTIL_BOX, BOX_APPROACH),
        dan dropdown di panel misi harus cocok dengan ketiganya sekaligus —
        satu daftar yang lupa ikut diperbarui berarti operator memilih "Box hijau"
        lalu kapal mengejar box biru, tanpa error apa pun.
        """
        p = str(nilai or default).strip().lower()
        if p in ("blue", "biru", "blue_box"):
            return "blue"
        if p in ("green", "hijau", "ijo", "green_box"):
            return "green"
        return p

    def _steer_box_target_mode(self, step: Dict) -> str:
        """
        "blue" | "green" | "both" | "any" dari field `target` STEER_UNTIL_BOX.

        Nilai asing jatuh ke "any" — sama seperti field yang dikosongkan. Dipisah
        jadi fungsi sendiri dengan alasan yang sama seperti _photo_urutan_target.
        """
        pilihan = self._target_box_normal(step.get("target"), "any")
        return pilihan if pilihan in ("blue", "green", "both") else "any"

    @staticmethod
    def _dock_prefer_normal(nilai) -> str:
        """Ejaan apa pun untuk sisi docking → "left" | "right" | "auto"."""
        p = str(nilai or "auto").strip().lower()
        if p in ("left", "kiri"):
            return "left"
        if p in ("right", "kanan"):
            return "right"
        return "auto"

    def _bap_peran_target(self, step: Dict) -> str:
        """Warna box yang dicari step ini. Default biru, sesuai alur lomba."""
        if self._target_box_normal(step.get("target"), "blue") == "green":
            return ROLE_GREEN_BOX
        return ROLE_BLUE_BOX

    def _bap_box_terdekat(self, detected_boxes: Dict, peran: str, min_area: float):
        """
        Box target dengan bbox TERBESAR (= paling dekat), atau None.

        Dipilih yang terbesar, bukan yang pertama dari YOLO: urutan keluaran YOLO
        tidak menjamin apa pun, dan mengunci box yang jauh saat ada yang dekat
        membuat kapal melewati sasaran yang benar.
        """
        terbaik = None
        luas_terbaik = 0.0
        for b in (detected_boxes.get(peran) or []):
            luas = self._bbox_area(b)
            if luas >= min_area and luas > luas_terbaik:
                luas_terbaik = luas
                terbaik = b
        return terbaik

    def _bap_throttle(self, step: Dict, key: str, default: float) -> float:
        """Throttle dari field step, dijepit ke 0..1."""
        return max(0.0, min(1.0, self._safe_float(step.get(key), default)))

    def _bap_mencari(self, step: Dict, sekarang: float) -> Tuple[float, float, str]:
        """Box target tidak terlihat: sapu ke arah yang diminta, lalu menyerah."""
        # Kedip deteksi sesaat saat sedang mendekat: pertahankan kemudi terakhir
        # supaya kapal tidak meluruskan haluan tiap kali YOLO berkedip satu frame.
        if self._bap_phase == self.BAP_APPROACH:
            jeda = self._safe_float(step.get("lost_grace_sec"), self.BAP_LOST_GRACE_SEC)
            if self._bap_last_seen_at > 0.0 and (sekarang - self._bap_last_seen_at) < jeda:
                thr = self._bap_throttle(step, "approach_throttle",
                                         self.BAP_APPROACH_THROTTLE)
                return self._bap_last_steer, thr, "BOX_APPROACH | box hilang sekejap"
            self._bap_set_phase(self.BAP_SCAN)
        else:
            self._bap_set_phase(self.BAP_SCAN)

        lama = sekarang - self._bap_phase_since
        batas = self._safe_float(step.get("scan_timeout_sec"), self.BAP_SCAN_TIMEOUT_SEC)
        if batas > 0 and lama >= batas:
            # Diselesaikan, BUKAN digantung: kapal yang menyapu tanpa batas akan
            # keluar arena, dan misi yang menggantung tidak pernah sampai FINISH.
            print(f"[MissionEngine] ⏱️ BOX_APPROACH selesai — box tidak ketemu "
                  f"dalam {lama:.0f}s.")
            self._advance_step()
            return 0.0, 0.0, "BOX_APPROACH | TIDAK KETEMU"

        steer = max(-1.0, min(1.0, self._safe_float(step.get("scan_steer"),
                                                    self.BAP_SCAN_STEER)))
        thr = self._bap_throttle(step, "scan_throttle", self.BAP_SCAN_THROTTLE)
        arah = "←" if steer < -0.05 else ("→" if steer > 0.05 else "↑")
        sisa = f"{max(0.0, batas - lama):.0f}s" if batas > 0 else "∞"
        return steer, thr, f"BOX_APPROACH | SCAN {arah} sisa {sisa}"

    def _bap_arah_menghindar(self, step: Dict, peran: str) -> float:
        """
        Tanda kemudi manuver menghindar: -1 ke KIRI, +1 ke KANAN.

        "auto" memakai konvensi sisi (vision/gate_convention.py): box biru menandai
        tepi KANAN lintasan sehingga kapal menghindar ke KIRI, hijau sebaliknya.
        Arah eksplisit selalu menang atas konvensi — operator yang mengetik "kanan"
        pasti sedang menangani kasus yang tidak diketahui kode ini.
        """
        arah = str(step.get("evade_direction") or self.BAP_EVADE_DIRECTION).strip().lower()
        if arah in ("right", "kanan", "r", "+1"):
            return 1.0
        if arah in ("left", "kiri", "l", "-1"):
            return -1.0
        if arah == "auto":
            return float(channel_sign(peran))
        # Salah ketik jangan diam-diam jadi "kanan": jatuh ke default yang aman.
        return -1.0 if str(self.BAP_EVADE_DIRECTION).lower().startswith("l") else 1.0

    def _bap_mulai_menghindar(self, step: Dict, sekarang: float, peran: str,
                              alasan: str) -> Tuple[float, float, str]:
        """
        Syarat menghindar terpenuhi.

        Arah & kekuatan bantingan dikunci SEKARANG, selagi box masih terlihat: begitu
        kapal membanting — atau berhenti untuk memotret — box bisa keluar frame, dan
        arah yang dihitung ulang saat itu tidak lagi punya dasar.

        Kalau step diminta memotret, fase SHOOT disisipkan dulu di sini. Kalau tidak
        (default), langsung menghindar.
        """
        kuat = min(1.0, abs(self._safe_float(step.get("evade_steer"), self.BAP_EVADE_STEER)))
        self._bap_evade_steer = self._bap_arah_menghindar(step, peran) * kuat
        self._bap_evade_reason = alasan
        self._bap_target_peran = peran
        arah_lbl = "KANAN" if self._bap_evade_steer > 0 else "KIRI"

        mode_foto = self._bap_mode_foto(step)
        if mode_foto is None:
            self._bap_set_phase(self.BAP_EVADE)
            print(f"[MissionEngine] ↩️ {ROLE_LABELS[peran]} — {alasan}. "
                  f"Menghindar ke {arah_lbl}.")
            return self._bap_menghindar(step, sekarang)

        self._bap_shutter_diminta = False
        self._bap_set_phase(self.BAP_SHOOT)
        print(f"[MissionEngine] 📷 {ROLE_LABELS[peran]} — {alasan}. Memotret "
              f"({mode_foto}), lalu menghindar ke {arah_lbl}.")
        return self._bap_memotret(step, sekarang)

    def _bap_mode_foto(self, step: Dict) -> Optional[str]:
        """
        "stop" | "moving" kalau step diminta memotret, None kalau tidak.

        Nilai yang tidak dikenali dianggap TIDAK memotret, bukan memotret: salah ketik
        pada field ini paling aman kalau berakhir pada perilaku default step.
        """
        mode = str(step.get("photo") or self.BAP_PHOTO_MODE).strip().lower()
        if mode in ("stop", "berhenti", "diam"):
            return "stop"
        if mode in ("moving", "jalan", "bergerak", "move"):
            return "moving"
        return None

    def _bap_memotret(self, step: Dict, sekarang: float) -> Tuple[float, float, str]:
        """
        Minta shutter, tunggu main.py mengambil frame BERSIH, lalu lanjut menghindar.

        Mekanismenya sama persis dengan TAKE_IMAGE dan BOX_CHANNEL: engine cuma
        menyalakan _capture_pending, dan main.py yang memanggil capture_now() dengan
        frame yang belum digambari anotasi YOLO/OSD.
        """
        mode = self._bap_mode_foto(step) or "moving"
        label = ROLE_LABELS.get(self._bap_target_peran, "box")
        lama = sekarang - self._bap_phase_since

        # --- Mode stop: berhenti dan tunggu kapal benar-benar diam dulu ---
        if mode == "stop" and not self._bap_shutter_diminta:
            if self.asv and self.asv.is_connected():
                self.asv.stop_movement(silent=True)
            tunggu = max(0.0, self._safe_float(step.get("photo_settle_sec"),
                                               self.BAP_PHOTO_SETTLE_SEC))
            if lama < tunggu:
                return 0.0, 0.0, (f"BOX_APPROACH | SETTLE {label} "
                                  f"{lama:.1f}/{tunggu:.1f}s")

        # --- Minta shutter, sekali saja ---
        if not self._bap_shutter_diminta:
            self._capture_requested_at = sekarang
            self._capture_pending = True
            self._capture_label = self._bap_target_peran
            self._bap_shutter_diminta = True
            self._bap_shutter_sejak = sekarang
            print(f"[MissionEngine] 📸 Memotret {label}"
                  f"{' (sambil jalan)' if mode == 'moving' else ''}...")

        # --- Foto sudah diambil → menghindar ---
        if not self._capture_pending:
            print(f"[MissionEngine] ✅ Foto {label} tersimpan — menghindar.")
            self._bap_set_phase(self.BAP_EVADE)
            return self._bap_menghindar(step, sekarang)

        # --- Kamera tidak pernah menyerahkan frame bersih ---
        if (sekarang - self._bap_shutter_sejak) >= self.BAP_SHOOT_TIMEOUT_SEC:
            self._capture_pending = False
            print(f"[MissionEngine] ⚠️ Foto {label} GAGAL — tidak ada frame kamera. "
                  f"Tetap menghindar.")
            self._bap_set_phase(self.BAP_EVADE)
            return self._bap_menghindar(step, sekarang)

        # --- Menunggu shutter: tahan posisi sesuai modenya ---
        if mode == "stop":
            if self.asv and self.asv.is_connected():
                self.asv.stop_movement(silent=True)
            return 0.0, 0.0, f"BOX_APPROACH | SHOOT {label}"
        thr = self._bap_throttle(step, "approach_throttle", self.BAP_APPROACH_THROTTLE)
        return self._bap_last_steer, thr, f"BOX_APPROACH | SHOOT {label} (jalan)"

    def _bap_menghindar(self, step: Dict, sekarang: float) -> Tuple[float, float, str]:
        """Tahan bantingan selama durasi yang diminta, lalu selesaikan step."""
        durasi = max(0.0, self._safe_float(step.get("evade_sec"), self.BAP_EVADE_SEC))
        lama = sekarang - self._bap_phase_since
        if lama < durasi:
            thr = self._bap_throttle(step, "evade_throttle", self.BAP_EVADE_THROTTLE)
            arah = "KANAN" if self._bap_evade_steer > 0 else "KIRI"
            return self._bap_evade_steer, thr,                 f"BOX_APPROACH | EVADE {arah} {lama:.1f}/{durasi:.1f}s"

        print(f"[MissionEngine] ✅ BOX_APPROACH selesai — manuver menghindar "
              f"{durasi:.1f}s tuntas.")
        self._advance_step()
        return 0.0, 0.0, "BOX_APPROACH | SELESAI"

    def _bap_set_phase(self, fase: str):
        if self._bap_phase != fase:
            self._bap_phase = fase
            self._bap_phase_since = time.time()

    # ------------------------------------------------------------------ #
    #  DOCKING — tabrak 2 dari 3 bola biru yang berjajar                  #
    # ------------------------------------------------------------------ #

    def docking(self, step: Dict, detected_balls: Optional[Dict] = None
                ) -> Tuple[float, float, str]:
        """
        Manuver docking: menabrak DUA dari tiga bola biru yang berjajar.

            SEARCH ──► ACQUIRE ──► ALIGN ──► RAM ──► step selesai
                       (kunci sisi)

        KENAPA HARUS MEMILIH, BUKAN MEMBIDIK TENGAH: lambung 0,40 m lebih sempit
        daripada rentang ketiga bola 0,60 m, jadi ketiganya mustahil kena sekaligus.
        Membidik bola TENGAH malah yang terburuk — lambung menutup [-0,20 .. +0,20]
        sementara bola luar ada di ±0,30, jadi cuma SATU bola yang kena. Membidik
        titik tengah salah satu pasangan bersebelahan menutup tepat DUA.

        KENAPA SISINYA DIKUNCI SEKALI: titik bidik berjarak 0,15 m ke masing-masing
        bola sasaran sementara setengah lambung 0,20 m, jadi toleransi melencengnya
        cuma 0,05 m (lebih longgar sebesar jari-jari bola). Berpindah pasangan di
        tengah pendekatan menggeser haluan 0,30 m — enam kali lipat seluruh toleransi
        yang tersedia. Sekali dikunci, sisi itu tidak pernah berubah lagi.

        IDENTITAS KIRI/TENGAH/KANAN berasal dari POSISI X di frame, bukan dari kelas:
        ketiganya kelas yang sama persis (bola biru). Karena itu penguncian menunggu
        sampai KETIGANYA terlihat — dengan dua bola saja, tidak ada cara membedakan
        pasangan (kiri,tengah) dari (tengah,kanan).

        Field step yang bisa di-tuning (semua opsional, di-parse aman):

          --- Geometri arena ---
          ball_spacing_m        jarak antar pusat bola (default 0.30)
          boat_beam_m           lebar lambung (default 0.40)
          ball_diameter_m       diameter bola; 0 = belum diukur

          --- Pemilihan sasaran ---
          prefer                "auto" (default) | "left"/"kiri" | "right"/"kanan"
          lock_confirm_sec      lama ketiga bola harus terlihat sebelum dikunci
          min_detect_area_px2   bbox di bawah ini bukan bola

          --- Fase SEARCH ---
          search_throttle, search_steer, search_timeout_sec

          --- Fase ALIGN ---
          approach_throttle, steer_gain, max_steer
          align_tolerance_px    toleransi pemusatan sebelum boleh menabrak
          lost_grace_sec        bola hilang sekejap → tahan kemudi terakhir

          --- Fase RAM ---
          ram_area_px2          sasaran sedekat ini → berhenti mengoreksi, tabrak
          ram_throttle, ram_sec

          --- Pengaman ---
          max_duration_sec      batas keras seluruh step

        :param detected_balls: {"blue": [...], ...} dari tracker.
        :return: (steer_norm, thr_norm, label)
        """
        detected_balls = detected_balls or {}
        sekarang = time.time()

        batas_step = self._safe_float(step.get("max_duration_sec"), self.DOCK_MAX_DURATION_SEC)
        if batas_step > 0 and self._step_start_time:
            if (sekarang - self._step_start_time) >= batas_step:
                print(f"[MissionEngine] ⏱️ DOCKING dihentikan — batas {batas_step:.0f}s "
                      f"terlampaui di fase {self._dock_phase}.")
                self._advance_step()
                return 0.0, 0.0, "DOCKING | BATAS WAKTU"

        # RAM didahulukan: meter terakhir memang ditempuh tanpa penglihatan, jadi
        # deteksi yang muncul-hilang tidak boleh lagi mengubah apa pun.
        if self._dock_phase == self.DOCK_RAM:
            return self._dock_menabrak(step, sekarang)

        bolas = self._dock_bola(step, detected_balls)
        if not bolas:
            return self._dock_mencari(step, sekarang)

        self._dock_last_seen_at = sekarang

        if self._dock_pilihan is None:
            return self._dock_mengunci(step, sekarang, bolas)

        return self._dock_membidik(step, sekarang, bolas)

    def _handle_docking(self, step, frame, gate_x, detected_balls):
        """Adapter dispatch update_frame → docking(); rekursi saat step selesai."""
        idx_sebelum = self._current_step_idx
        hasil = self.docking(step, detected_balls)
        if self._current_step_idx != idx_sebelum:
            return self.update_frame(frame, gate_x, detected_balls)
        return hasil

    def _dock_bola(self, step: Dict, detected_balls: Dict) -> List:
        """
        Sampai TIGA bola biru terbesar, diurutkan KIRI→KANAN.

        Diambil yang terbesar (paling dekat) lalu diurutkan posisi, karena identitas
        kiri/tengah/kanan di step ini murni soal urutan X — ketiganya kelas yang sama.
        Deteksi keempat dan seterusnya pasti palsu: arena cuma punya tiga.
        """
        min_area = self._area_dari_step(step, "min_detect_area_px2",
                                        self.DOCK_MIN_DETECT_AREA_PX2)
        kandidat = [b for b in (detected_balls.get("blue") or [])
                    if self._bbox_area(b) >= min_area]
        kandidat.sort(key=self._bbox_area, reverse=True)
        return sorted(kandidat[:3], key=lambda b: b[0])

    def _dock_steer(self, step: Dict, error_px: float) -> float:
        gain = self._safe_float(step.get("steer_gain"), self.DOCK_STEER_GAIN)
        batas = min(1.0, abs(self._safe_float(step.get("max_steer"), self.DOCK_MAX_STEER)))
        s = (gain * error_px) / max(1.0, self.camera_width / 2.0)
        return max(-batas, min(batas, s))

    def _dock_throttle(self, step: Dict, key: str, default: float) -> float:
        return max(0.0, min(1.0, self._safe_float(step.get(key), default)))

    def _dock_laporkan_geometri(self, step: Dict):
        """
        Cetak toleransi melenceng yang SEBENARNYA saat step dimulai.

        Angkanya bergantung pada ukuran kapal dan arena yang bisa diubah operator,
        dan 5 cm sangat berbeda artinya dari 15 cm. Menghitungnya di sini membuat
        setelan yang mustahil (lambung lebih sempit dari jarak antar bola) ketahuan
        di dermaga, bukan setelah kapal gagal menabrak apa pun.
        """
        jarak = self._safe_float(step.get("ball_spacing_m"), self.DOCK_BALL_SPACING_M)
        lambung = self._safe_float(step.get("boat_beam_m"), self.DOCK_BOAT_BEAM_M)
        diameter = max(0.0, self._safe_float(step.get("ball_diameter_m"),
                                             self.DOCK_BALL_DIAMETER_M))
        toleransi = (lambung / 2.0) - (jarak / 2.0) + (diameter / 2.0)
        print(f"[MissionEngine] ⚓ DOCKING — bola tiap {jarak*100:.0f} cm, lambung "
              f"{lambung*100:.0f} cm → membidik titik tengah pasangan menutup 2 bola.")
        if toleransi <= 0:
            print(f"[MissionEngine] ⛔ DOCKING: lambung terlalu sempit "
                  f"({lambung*100:.0f} cm) untuk menjangkau dua bola berjarak "
                  f"{jarak*100:.0f} cm. Manuver ini TIDAK MUNGKIN mengenai dua bola.")
        else:
            print(f"[MissionEngine] 📏 Toleransi melenceng ke samping: "
                  f"{toleransi*100:.0f} cm"
                  f"{' (belum termasuk jari-jari bola — isi ball_diameter_m)' if diameter <= 0 else ''}.")

    def _dock_mencari(self, step: Dict, sekarang: float) -> Tuple[float, float, str]:
        """Tidak ada bola biru terlihat: sapu, lalu menyerah kalau tidak ketemu."""
        # Kedip deteksi saat sudah membidik: tahan kemudi terakhir. Meluruskan haluan
        # di sini berarti kehilangan pembidikan yang toleransinya cuma 5 cm.
        if self._dock_phase in (self.DOCK_ALIGN, self.DOCK_ACQUIRE):
            jeda = self._safe_float(step.get("lost_grace_sec"), self.DOCK_LOST_GRACE_SEC)
            if self._dock_last_seen_at > 0.0 and (sekarang - self._dock_last_seen_at) < jeda:
                thr = self._dock_throttle(step, "approach_throttle",
                                          self.DOCK_APPROACH_THROTTLE)
                return self._dock_last_steer, thr, "DOCKING | bola hilang sekejap"
            if self._dock_pilihan is not None:
                # Sasaran sudah dikunci dan bola hilang lebih lama dari toleransi —
                # pada jarak sedekat ini bola memang tenggelam di bawah haluan.
                # Menabrak dengan haluan terakhir jauh lebih baik daripada mencari
                # ulang dari nol dan kehilangan pembidikan yang sudah benar.
                return self._dock_mulai_menabrak(step, sekarang, self._dock_last_steer,
                                                 "bola hilang di jarak dekat")

        self._dock_set_phase(self.DOCK_SEARCH)
        lama = sekarang - self._dock_phase_since
        batas = self._safe_float(step.get("search_timeout_sec"), self.DOCK_SEARCH_TIMEOUT_SEC)
        if batas > 0 and lama >= batas:
            print(f"[MissionEngine] ⏱️ DOCKING selesai — area docking tidak ketemu "
                  f"dalam {lama:.0f}s.")
            self._advance_step()
            return 0.0, 0.0, "DOCKING | TIDAK KETEMU"

        steer = max(-1.0, min(1.0, self._safe_float(step.get("search_steer"),
                                                    self.DOCK_SEARCH_STEER)))
        thr = self._dock_throttle(step, "search_throttle", self.DOCK_SEARCH_THROTTLE)
        arah = "←" if steer < -0.05 else ("→" if steer > 0.05 else "↑")
        return steer, thr, f"DOCKING | SEARCH {arah} {lama:.0f}/{batas:.0f}s"

    def _dock_mengunci(self, step: Dict, sekarang: float, bolas: List
                       ) -> Tuple[float, float, str]:
        """Tunggu ketiga bola terlihat stabil, lalu pilih sisi dan KUNCI selamanya."""
        setengah = self.camera_width / 2.0
        thr = self._dock_throttle(step, "approach_throttle", self.DOCK_APPROACH_THROTTLE)
        self._dock_set_phase(self.DOCK_ACQUIRE)

        if len(bolas) < 3:
            # Dua bola tidak cukup: (kiri,tengah) dan (tengah,kanan) terlihat sama
            # persis. Dekati pusat kelompoknya supaya bola ketiga masuk frame.
            self._dock_bertiga_sejak = None
            pusat = sum(b[0] for b in bolas) / len(bolas)
            steer = self._dock_steer(step, pusat - setengah)
            self._dock_last_steer = steer
            return steer, thr, f"DOCKING | ACQUIRE {len(bolas)}/3 bola"

        if self._dock_bertiga_sejak is None:
            self._dock_bertiga_sejak = sekarang
        lama = sekarang - self._dock_bertiga_sejak
        tunggu = max(0.0, self._safe_float(step.get("lock_confirm_sec"),
                                           self.DOCK_LOCK_CONFIRM_SEC))
        if lama < tunggu:
            # Menuju bola TENGAH selama menunggu: dari sana kedua opsi sama-sama
            # sedekat mungkin, apa pun yang nanti terpilih.
            steer = self._dock_steer(step, bolas[1][0] - setengah)
            self._dock_last_steer = steer
            return steer, thr, f"DOCKING | ACQUIRE 3/3 {lama:.1f}/{tunggu:.1f}s"

        mid_kiri = (bolas[0][0] + bolas[1][0]) / 2.0
        mid_kanan = (bolas[1][0] + bolas[2][0]) / 2.0

        diminta = self._dock_prefer_normal(step.get("prefer") or self.DOCK_PREFER)
        if diminta == "left":
            self._dock_pilihan, self._dock_alasan = "left", "diminta operator"
        elif diminta == "right":
            self._dock_pilihan, self._dock_alasan = "right", "diminta operator"
        elif abs(mid_kiri - setengah) <= abs(mid_kanan - setengah):
            self._dock_pilihan, self._dock_alasan = "left", "perubahan haluan terkecil"
        else:
            self._dock_pilihan, self._dock_alasan = "right", "perubahan haluan terkecil"

        # Rasio jarak-antar-bola terhadap lebar bola, direkam SELAGI ketiganya
        # terlihat. Nanti dipakai mengenali apakah dua bola yang tersisa itu
        # bersebelahan atau justru pasangan LUAR — lihat _dock_titik_bidik.
        self._dock_rasio_pasangan = self._dock_rasio(bolas[0], bolas[1], bolas[2])

        bidik = mid_kiri if self._dock_pilihan == "left" else mid_kanan
        self._dock_bidik_px = bidik
        self._dock_set_phase(self.DOCK_ALIGN)
        sisi = "KIRI+TENGAH" if self._dock_pilihan == "left" else "TENGAH+KANAN"
        print(f"[MissionEngine] ⚓ DOCKING mengunci sasaran: {sisi} "
              f"({self._dock_alasan}). Titik bidik x={bidik:.0f}px.")
        return self._dock_membidik(step, sekarang, bolas)

    @staticmethod
    def _dock_rasio(kiri, tengah, kanan) -> float:
        """
        Jarak antar bola BERSEBELAHAN dibagi lebar rata-rata bola.

        Rasio, bukan piksel mentah: keduanya membesar bersamaan saat kapal mendekat,
        jadi perbandingannya tetap walau jaraknya berubah — tidak perlu tahu jarak
        kapal ke bola sama sekali.
        """
        lebar = [(b[4] - b[2]) for b in (kiri, tengah, kanan)]
        lebar_rata = sum(lebar) / 3.0
        jarak_rata = ((tengah[0] - kiri[0]) + (kanan[0] - tengah[0])) / 2.0
        return jarak_rata / max(1.0, lebar_rata)

    def _dock_titik_bidik(self, step: Dict, bolas: List) -> Optional[float]:
        """
        Titik bidik untuk frame ini, sesuai sisi yang SUDAH dikunci.

        Tiga bola terlihat: langsung titik tengah pasangan yang dipilih.

        DUA bola terlihat — di sinilah jebakannya. Kalau yang hilang adalah bola
        TENGAH, yang tersisa adalah pasangan LUAR, dan titik tengah keduanya justru
        menunjuk tepat ke posisi bola tengah. Membidik ke sana membuat lambung
        menutup [-0,20 .. +0,20] sementara bola luar ada di ±0,30 — cuma SATU bola
        yang kena, padahal ketiganya terlihat sesaat sebelumnya. Pasangan luar
        dikenali dari rasio jaraknya (dua kali lipat pasangan bersebelahan), lalu
        posisi bola tengah direkonstruksi darinya.

        SATU bola terlihat: butuh diameter bola untuk memperkirakan jaraknya. Tanpa
        itu, kemudi terakhir yang dipertahankan — menebak di sini berarti menggeser
        haluan lebih jauh daripada seluruh toleransi yang tersedia.
        """
        if len(bolas) >= 3:
            return ((bolas[0][0] + bolas[1][0]) / 2.0 if self._dock_pilihan == "left"
                    else (bolas[1][0] + bolas[2][0]) / 2.0)

        if len(bolas) == 2:
            a, b = bolas[0][0], bolas[1][0]
            lebar_rata = ((bolas[0][4] - bolas[0][2]) + (bolas[1][4] - bolas[1][2])) / 2.0
            rasio = (b - a) / max(1.0, lebar_rata)
            acuan = self._dock_rasio_pasangan
            if acuan and rasio > acuan * 1.5:
                # Pasangan LUAR: bola tengah ada tepat di antaranya.
                tengah = (a + b) / 2.0
                return (a + tengah) / 2.0 if self._dock_pilihan == "left" else (tengah + b) / 2.0
            # Pasangan bersebelahan. Yang mana, dipastikan lewat kesinambungan:
            # pasangan yang keliru titik tengahnya melompat sejauh satu jarak bola.
            mid = (a + b) / 2.0
            if self._dock_bidik_px is not None and abs(mid - self._dock_bidik_px) > (b - a):
                return None
            return mid

        if len(bolas) == 1:
            offset = self._dock_offset_px(step, bolas[0])
            if offset <= 0 or self._dock_bidik_px is None:
                return None
            kandidat = (bolas[0][0] - offset, bolas[0][0] + offset)
            return min(kandidat, key=lambda x: abs(x - self._dock_bidik_px))

        return None

    def _dock_offset_px(self, step: Dict, bola) -> float:
        """
        Setengah jarak antar bola dalam piksel, dihitung dari lebar bola di layar.

        Sama caranya dengan _boxch_offset_px: memakai benda berukuran diketahui di
        frame ini sendiri, jadi hasilnya tetap sekian METER pada jarak berapa pun.
        """
        diameter = self._safe_float(step.get("ball_diameter_m"), self.DOCK_BALL_DIAMETER_M)
        jarak = self._safe_float(step.get("ball_spacing_m"), self.DOCK_BALL_SPACING_M)
        lebar_px = float(bola[4] - bola[2])
        if diameter <= 0 or jarak <= 0 or lebar_px <= 0:
            return 0.0
        return (lebar_px / diameter) * (jarak / 2.0)

    def _dock_membidik(self, step: Dict, sekarang: float, bolas: List
                       ) -> Tuple[float, float, str]:
        """Kemudikan ke titik bidik sampai sasaran terlalu dekat untuk dikoreksi."""
        bidik = self._dock_titik_bidik(step, bolas)
        if bidik is None:
            thr = self._dock_throttle(step, "approach_throttle", self.DOCK_APPROACH_THROTTLE)
            return self._dock_last_steer, thr, "DOCKING | ALIGN (bidikan ditahan)"

        self._dock_bidik_px = bidik
        self._dock_set_phase(self.DOCK_ALIGN)

        setengah = self.camera_width / 2.0
        error_px = bidik - setengah
        steer = self._dock_steer(step, error_px)
        self._dock_last_steer = steer

        # Sudah terlalu dekat untuk mengoreksi apa pun: bola akan keluar frame
        # (atau tenggelam di bawah haluan) sebelum benturannya terjadi.
        luas_terbesar = max(self._bbox_area(b) for b in bolas)
        ambang_ram = self._area_dari_step(step, "ram_area_px2", self.DOCK_RAM_AREA_PX2)
        if luas_terbesar >= ambang_ram:
            toleransi = self._px_dari_step(step, "align_tolerance_px",
                                           self.DOCK_ALIGN_TOLERANCE_PX)
            # Sudah lurus → tabrak lurus. Belum lurus → tabrak dengan kemudi terakhir,
            # karena mempertahankan koreksi lebih baik daripada meluruskan haluan
            # yang memang belum benar.
            if abs(error_px) <= toleransi:
                return self._dock_mulai_menabrak(step, sekarang, 0.0,
                                                 f"lurus ({error_px:+.0f}px) & sudah dekat")
            return self._dock_mulai_menabrak(step, sekarang, steer,
                                             f"sudah dekat, sisa {error_px:+.0f}px")

        thr = self._dock_throttle(step, "approach_throttle", self.DOCK_APPROACH_THROTTLE)
        sisi = "KIRI+TENGAH" if self._dock_pilihan == "left" else "TENGAH+KANAN"
        return steer, thr, (f"DOCKING | ALIGN {sisi} err={error_px:+.0f}px "
                            f"({len(bolas)} bola)")

    def _dock_mulai_menabrak(self, step: Dict, sekarang: float, steer: float,
                             alasan: str) -> Tuple[float, float, str]:
        self._dock_ram_steer = max(-1.0, min(1.0, steer))
        self._dock_alasan = alasan
        self._dock_set_phase(self.DOCK_RAM)
        sisi = ("KIRI+TENGAH" if self._dock_pilihan == "left"
                else "TENGAH+KANAN" if self._dock_pilihan == "right" else "?")
        print(f"[MissionEngine] 💥 DOCKING menabrak {sisi} — {alasan}.")
        return self._dock_menabrak(step, sekarang)

    def _dock_menabrak(self, step: Dict, sekarang: float) -> Tuple[float, float, str]:
        """Meter terakhir ditempuh tanpa penglihatan, lalu step selesai."""
        durasi = max(0.0, self._safe_float(step.get("ram_sec"), self.DOCK_RAM_SEC))
        lama = sekarang - self._dock_phase_since
        if lama < durasi:
            thr = self._dock_throttle(step, "ram_throttle", self.DOCK_RAM_THROTTLE)
            return self._dock_ram_steer, thr, f"DOCKING | RAM {lama:.1f}/{durasi:.1f}s"

        print(f"[MissionEngine] ✅ DOCKING selesai — manuver menabrak {durasi:.1f}s tuntas.")
        self._advance_step()
        return 0.0, 0.0, "DOCKING | SELESAI"

    def _dock_set_phase(self, fase: str):
        if self._dock_phase != fase:
            self._dock_phase = fase
            self._dock_phase_since = time.time()

    def _reset_dock_state(self):
        """Kembalikan state DOCKING ke awal. Dipanggil saat step ini dimulai."""
        self._dock_phase = self.DOCK_SEARCH
        self._dock_phase_since = time.time()
        self._dock_pilihan = None
        self._dock_alasan = ""
        self._dock_bidik_px = None
        self._dock_last_steer = 0.0
        self._dock_last_seen_at = 0.0
        self._dock_bertiga_sejak = None
        self._dock_ram_steer = 0.0
        self._dock_rasio_pasangan = 0.0

    def _reset_bap_state(self):
        """Kembalikan state BOX_APPROACH ke awal. Dipanggil saat step ini dimulai."""
        self._bap_phase = self.BAP_SCAN
        self._bap_phase_since = time.time()
        self._bap_last_seen_at = 0.0
        self._bap_last_steer = 0.0
        self._bap_evade_steer = 0.0
        self._bap_evade_reason = ""
        self._bap_target_peran = ROLE_BLUE_BOX
        self._bap_shutter_diminta = False
        self._bap_shutter_sejak = 0.0

    def _handle_hold(self, step, frame, gate_x, detected_balls=None):
        """Handle HOLD step."""
        duration = self._safe_float(step.get("duration_sec"), 5.0)
        elapsed = time.time() - self._step_start_time

        if elapsed >= duration:
            print(f"[MissionEngine] ✅ HOLD selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x, detected_balls)

        # Kirim perintah stop berulang setiap frame agar motor betul-betul berhenti
        # (MAVLink GUIDED velocity = 0, tidak membutuhkan RC override)
        if self.asv and self.asv.is_connected():
            self.asv.stop_movement(silent=True)

        remaining = max(0.0, duration - elapsed)
        return 0.0, 0.0, f"HOLD | rem={remaining:.1f}s"

    # ------------------------------------------------------------------ #
    #  Dynamic Movement Handlers                                         #
    # ------------------------------------------------------------------ #

    def _handle_custom_forward(self, step: Dict) -> Tuple[float, float, str]:
        """
        Handle CUSTOM_FORWARD step.

        Kapal bergerak maju dengan kecepatan `speed_mps` (m/s) selama `duration_sec` detik.
        Selama bergerak, `heading_offset_deg` diterapkan sebagai yaw rate konstan (°/s):
          - heading_offset_deg = 0  → maju lurus
          - heading_offset_deg = +5 → condong kanan 5°/s (lintasan serong kanan)
          - heading_offset_deg = -5 → condong kiri 5°/s (lintasan serong kiri)

        Gerak dikirim via NavigationControl.send_velocity() → MAVLink SET_POSITION_TARGET_LOCAL_NED
        dalam mode GUIDED. TIDAK ADA direct PWM/servo override.

        Variabel step yang digunakan:
          step['speed_mps']          (float) — Kecepatan maju dalam m/s. Default: 0.5
          step['heading_offset_deg'] (float) — Yaw rate konstan (°/s). Default: 0.0
          step['duration_sec']       (float) — Batas waktu dalam detik. Default: 5.0
        """
        speed_mps          = self._safe_float(step.get("speed_mps"), 0.5)
        heading_offset_deg = self._safe_float(step.get("heading_offset_deg"), 0.0)
        duration_sec       = self._safe_float(step.get("duration_sec"), 5.0)

        elapsed = time.time() - self._step_start_time

        # Cek kondisi selesai berdasarkan timer
        if elapsed >= duration_sec:
            print(f"[MissionEngine] ✅ CUSTOM_FORWARD selesai! Durasi {duration_sec:.1f}s terpenuhi.")
            self.asv.stop_movement()
            self._advance_step()
            return 0.0, 0.0, "CUSTOM_FORWARD"

        # Kirim perintah gerak: maju dengan yaw rate = heading_offset_deg
        # Gerakan dikontrol oleh send_velocity() di mode GUIDED — bukan RC override.
        # Mode switch sudah dilakukan di init block (step_start_time is None).
        self.asv.nav.send_velocity(
            forward_speed=speed_mps,
            turn_rate_deg=heading_offset_deg
        )

        remaining = max(0.0, duration_sec - elapsed)
        offset_label = f"+{heading_offset_deg:.1f}°" if heading_offset_deg >= 0 else f"{heading_offset_deg:.1f}°"
        label = (f"CUSTOM_FORWARD | spd={speed_mps:.1f}m/s offset={offset_label} "
                 f"rem={remaining:.1f}s")
        # Return (0.0, 0.0) — movement via send_velocity(), NOT RC override.
        # main.py hanya kirim send_manual_rc_drive saat thr_norm > 0 atau mode MANUAL.
        return 0.0, 0.0, label

    def _handle_gyro_forward(self, step: Dict, detected_balls: Dict) -> Tuple[float, float, str]:
        """
        Handle GYRO_FORWARD step.

        Konsepnya SAMA PERSIS dengan TRACKING_BUOY: mode MANUAL, kapal digerakkan via
        RC Override (steer_norm -1..+1, throttle_norm 0..1 lewat send_manual_rc_drive) —
        BUKAN GUIDED/send_velocity(). Satu-satunya yang beda: sumber error steering-nya
        BUKAN posisi bola di kamera (piksel), melainkan error heading kompas/gyro
        (derajat) terhadap heading awal saat step ini dimulai (heading-hold). throttle
        dipertahankan konstan sepanjang step, sama seperti throttle konstan di TRACKING_BUOY.

        Heading awal direkam sebagai target di frame pertama, lalu tiap frame error
        terhadap heading itu dikoreksi proporsional (steer_norm = Kp × heading_error,
        di-clamp ke ±1.0, dengan dead-zone kecil agar tidak jitter saat hampir lurus —
        pola yang sama seperti TrackingController.compute_normalized_steering()).

        Step SELESAI jika salah satu terjadi lebih dulu:
          - duration_sec terlampaui (safety cap / cruise dianggap gagal menemukan buoy), ATAU
          - bola (merah ATAU hijau, apa saja) terdeteksi TERUS-MENERUS selama
            GYRO_FORWARD_BALL_CONFIRM_SEC (debounce — mencegah 1 frame false-positive YOLO
            memotong cruise sebelum benar-benar sampai di depan gerbang buoy). Begitu
            confirmed, step berikutnya (biasanya TRACKING_BUOY/SEQUENTIAL_BUOY) mengambil alih.
            Kondisi ini HANYA dicek setelah min_runtime_sec terlampaui — mencegah step
            langsung selesai dalam <1 detik (kapal belum sempat maju sama sekali) kalau
            buoy/false-positive KEBETULAN sudah kelihatan tepat saat step baru mulai
            (mis. posisi start terlalu dekat gerbang, atau glare/pantulan air).

        Variabel step yang digunakan:
          step['throttle']             (float) — Throttle 0.0-1.0. OPSIONAL — fallback ke
                                        speed_scheduler.max_base_throttle jika kosong
                                        (lihat _resolve_step_throttle(), sama seperti
                                        TRACKING_BUOY/SEQUENTIAL_BUOY).
          step['duration_sec']         (float) — Batas waktu maksimum (detik). Default: 15.0
          step['min_runtime_sec']      (float) — Waktu minimum maju sebelum deteksi buoy
                                        boleh mengakhiri step lebih awal. Default: 1.5
          step['heading_kp']           (float) — Gain proporsional: steer_norm per derajat
                                        error heading. Default: 0.03 (error 30° → steer ±0.9)
          step['heading_deadzone_deg'] (float) — Error di bawah ini dianggap lurus (tidak
                                        ada koreksi), mencegah micro-correction flicker.
                                        Default: 2.0
        """
        throttle             = self._resolve_step_throttle(step)
        duration_sec         = self._safe_float(step.get("duration_sec"), 15.0)
        min_runtime_sec      = self._safe_float(step.get("min_runtime_sec"), 1.5)
        heading_kp           = self._safe_float(step.get("heading_kp"), 0.03)
        heading_deadzone_deg = self._safe_float(step.get("heading_deadzone_deg"), 2.0)

        # Pastikan FC selalu di mode MANUAL, sama seperti TRACKING_BUOY/SEQUENTIAL_BUOY
        # (defensive re-check tiap frame, bukan cuma sekali di awal step).
        if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
            print("[MissionEngine] 🔄 Automatic mode switch to MANUAL for GYRO_FORWARD...")
            self.asv.set_mode("MANUAL")

        elapsed = time.time() - self._step_start_time

        # --- Selesai karena waktu habis (safety cap) ---
        if duration_sec > 0 and elapsed >= duration_sec:
            print(f"[MissionEngine] ✅ GYRO_FORWARD selesai! Durasi {duration_sec:.1f}s terpenuhi (timeout).")
            self._advance_step()
            return 0.0, 0.0, "GYRO_FORWARD"

        # --- Selesai karena buoy terdeteksi (confirmed, bukan 1 frame flicker, DAN kapal
        # sudah maju minimal min_runtime_sec) ---
        if elapsed >= min_runtime_sec:
            now = time.time()
            ball_visible_now = bool(detected_balls.get("red")) or bool(detected_balls.get("green"))
            if ball_visible_now:
                if self._cruise_ball_seen_since is None:
                    self._cruise_ball_seen_since = now
                elif (now - self._cruise_ball_seen_since) >= self.GYRO_FORWARD_BALL_CONFIRM_SEC:
                    print(f"[MissionEngine] ✅ GYRO_FORWARD selesai! Buoy terdeteksi di depan kamera.")
                    self._advance_step()
                    return 0.0, 0.0, "GYRO_FORWARD"
            else:
                self._cruise_ball_seen_since = None

        # --- Ambil heading saat ini & rekam heading-hold target di frame pertama ---
        telemetry = self.asv.get_telemetry() if self.asv else None
        current_heading = getattr(telemetry, "heading", None) if telemetry else None

        if self._cruise_initial_heading is None and current_heading is not None:
            self._cruise_initial_heading = float(current_heading)
            print(f"[MissionEngine] 🧭 GYRO_FORWARD dimulai: heading_hold={self._cruise_initial_heading:.1f}° "
                  f"thr={throttle:.2f}")

        remaining = max(0.0, duration_sec - elapsed)

        if self._cruise_initial_heading is None or current_heading is None:
            # Heading belum/tidak tersedia → tetap MAJU (steer netral) alih-alih diam total.
            # Kapal tidak boleh berhenti hanya karena data kompas belum siap.
            label = f"GYRO_FORWARD: NO_HEADING (maju lurus) thr={throttle:.2f} rem={remaining:.1f}s"
            return 0.0, throttle, label

        heading_error = self._angular_diff(float(current_heading), self._cruise_initial_heading)

        # Dead-zone: error kecil dianggap lurus — tidak ada micro-correction flicker.
        if abs(heading_error) < heading_deadzone_deg:
            steer_norm = 0.0
        else:
            steer_norm = max(-1.0, min(1.0, heading_kp * heading_error))

        label = (f"GYRO_FORWARD | thr={throttle:.2f} hdg={current_heading:.1f}° "
                 f"err={heading_error:+.1f}° steer={steer_norm:+.2f} rem={remaining:.1f}s")
        # steer_norm/throttle dikirim via RC Override (send_manual_rc_drive) oleh main.py,
        # SAMA seperti TRACKING_BUOY/SEQUENTIAL_BUOY/TIMED_STEER — bukan send_velocity().
        return steer_norm, throttle, label

    def _handle_precision_turn(self, step: Dict) -> Tuple[float, float, str]:
        """
        Handle PRECISION_TURN step.

        Kapal berputar di tempat hingga mencapai sudut `turn_angle_deg` dari heading awal.
        Menggunakan feedback `telemetry.heading` (0-360°) dari ArduPilot kompas/GPS untuk
        mengukur kemajuan belok secara akurat.

        Algoritma:
          1. Frame pertama: rekam `_turn_initial_heading` dari telemetry.heading
             Hitung `_turn_target_heading` = (initial + turn_angle_deg) % 360
          2. Setiap frame: hitung `heading_error` (selisih angular, range -180..+180)
             Positive error → perlu belok kanan lebih; negative error → perlu belok kiri.
          3. Jika abs(heading_error) <= TURN_ARRIVAL_THRESHOLD_DEG (3°): selesai → stop + advance.
          4. Jika belum: kirim yaw rate = sign(heading_error) × turn_rate_dps, forward_speed = 0.

        Variabel step yang digunakan:
          step['turn_angle_deg'] (float) — Sudut total belok. +90 = kanan 90°, -90 = kiri 90°. Default: 90
          step['turn_rate_dps']  (float) — Kecepatan rotasi dalam °/s. Default: 20

        Variabel state engine:
          self._turn_initial_heading (Optional[float]) — Heading awal saat step dimulai (0-360°).
          self._turn_target_heading  (Optional[float]) — Heading target setelah belok (0-360°).
        """
        turn_angle_deg = self._safe_float(step.get("turn_angle_deg"), 90.0)
        turn_rate_dps  = self._safe_float(step.get("turn_rate_dps"), 20.0)

        # Ambil telemetri untuk mendapatkan heading saat ini
        telemetry = self.asv.get_telemetry() if self.asv else None
        current_heading = getattr(telemetry, "heading", None) if telemetry else None

        # --- Inisialisasi target heading di frame pertama step ini ---
        if self._turn_initial_heading is None:
            if current_heading is None:
                # Belum ada data heading (GPS/kompas belum siap) — tunggu
                print("[MissionEngine] ⏳ PRECISION_TURN: Menunggu data heading dari telemetri...")
                return 0.0, 0.0, "PRECISION_TURN: WAITING_HEADING"

            self._turn_initial_heading = float(current_heading)
            # Target heading = initial + angle, dinormalisasi ke 0-360°
            self._turn_target_heading  = (self._turn_initial_heading + turn_angle_deg) % 360.0
            turn_dir_label = "CW (kanan)" if turn_angle_deg >= 0 else "CCW (kiri)"
            print(f"[MissionEngine] 🧭 PRECISION_TURN dimulai: "
                  f"initial={self._turn_initial_heading:.1f}° "
                  f"target={self._turn_target_heading:.1f}° "
                  f"({turn_dir_label}, {abs(turn_angle_deg):.1f}°)")

        # --- Hitung heading error (range -180..+180) ---
        if current_heading is None:
            # Kehilangan sinyal heading sementara — pertahankan yaw rate terakhir
            active_dir = math.copysign(turn_rate_dps, turn_angle_deg)
            self.asv.nav.send_velocity(forward_speed=0.0, turn_rate_deg=active_dir)
            return 0.0, 0.0, "PRECISION_TURN: HEADING_LOST"

        heading_error = self._angular_diff(float(current_heading), self._turn_target_heading)

        # --- Cek apakah sudah sampai target ---
        if abs(heading_error) <= self.TURN_ARRIVAL_THRESHOLD_DEG:
            print(f"[MissionEngine] ✅ PRECISION_TURN selesai! "
                  f"Heading={current_heading:.1f}° (target={self._turn_target_heading:.1f}°, "
                  f"error={heading_error:+.1f}°)")
            self.asv.stop_movement()
            self._advance_step()
            return 0.0, 0.0, "PRECISION_TURN"

        # --- Belum sampai: kirim yaw rate ke arah yang benar ---
        # sign(heading_error): positif = perlu belok kanan, negatif = perlu belok kiri
        yaw_direction = math.copysign(1.0, heading_error)
        self.asv.nav.send_velocity(
            forward_speed=0.0,
            turn_rate_deg=yaw_direction * turn_rate_dps
        )

        label = (f"PRECISION_TURN | hdg={current_heading:.1f}° "
                 f"target={self._turn_target_heading:.1f}° err={heading_error:+.1f}°")
        return 0.0, 0.0, label

    def _handle_timed_steer(self, step: Dict) -> Tuple[float, float, str]:
        """
        Handle TIMED_STEER step.

        Kapal bergerak dengan steer dan throttle yang ditentukan selama `duration_sec` detik
        menggunakan RC override pada mode MANUAL. Tidak ada feedback GPS/kompas — murni timer.

        Cocok untuk: belok kiri/kanan di tempat, maju sambil belok, atau gerak lurus singkat
        sebelum/sesudah TRACKING_BUOY tanpa perlu switch ke mode GUIDED.

        Variabel step yang digunakan:
          step['steer']        (float) — Steering normalized: -1.0 (kiri penuh) .. +1.0 (kanan penuh). Default: 0.0
          step['throttle']     (float) — Throttle ratio: 0.0 (berhenti) .. 1.0 (full maju). Default: 0.3
          step['duration_sec'] (float) — Durasi maneuver dalam detik. Default: 3.0
        """
        steer       = max(-1.0, min(1.0, self._safe_float(step.get("steer"), 0.0)))
        throttle    = max(0.0, min(1.0, self._safe_float(step.get("throttle"), 0.3)))
        duration_sec = self._safe_float(step.get("duration_sec"), 3.0)

        elapsed = time.time() - self._step_start_time

        if elapsed >= duration_sec:
            print(f"[MissionEngine] ✅ TIMED_STEER selesai! Durasi {duration_sec:.1f}s terpenuhi.")
            self._advance_step()
            return 0.0, 0.0, "TIMED_STEER"

        remaining = max(0.0, duration_sec - elapsed)
        dir_label = "←" if steer < -0.05 else ("→" if steer > 0.05 else "↑")
        label = (f"TIMED_STEER {dir_label} | steer={steer:+.2f} thr={throttle:.2f} "
                 f"rem={remaining:.1f}s")
        return steer, throttle, label

    def _gate_pair_visible(self, detected_balls: Dict, min_area_px2: float) -> Tuple[bool, bool]:
        """
        Apakah GERBANG terlihat: minimal SATU bola merah DAN satu bola hijau yang
        area bounding box-nya >= min_area_px2.

        Return (merah_terlihat, hijau_terlihat) — dipisah supaya label OSD bisa
        menunjukkan warna mana yang sudah/belum ketemu, bukan cuma "belum lengkap".

        Ambang area WAJIB ada: tanpa itu satu piksel pantulan air yang lolos YOLO
        sudah cukup dianggap "gerbang terlihat" dan memotong manuver lebih awal.
        """
        def _ada(balls) -> bool:
            return any(self._bbox_area(b) >= min_area_px2 for b in (balls or []))

        return _ada(detected_balls.get("red")), _ada(detected_balls.get("green"))

    def _handle_steer_until_gate(self, step: Dict, detected_balls: Dict) -> Tuple[float, float, str]:
        """
        Handle STEER_UNTIL_GATE step.

        PERSIS seperti TIMED_STEER — steer & throttle tetap lewat RC override di mode
        MANUAL, tanpa feedback GPS/kompas — dengan SATU tambahan: step selesai lebih
        awal begitu GERBANG terlihat, yaitu bola MERAH dan HIJAU terdeteksi
        BERSAMAAN. Bola satu warna saja TIDAK cukup.

        Kenapa harus dua warna, bukan "ada bola": satu bola saja tidak menentukan
        gerbang mana pun — bisa bola sisa gerbang yang baru dilewati, bola dari lintasan
        sebelah, atau pantulan. Menyerahkan kendali ke step berikutnya berdasarkan satu
        bola berarti step buoy-tracking berikutnya mulai tanpa gerbang yang utuh untuk
        dibidik. Dua warna sekaligus adalah syarat minimum sebuah gerbang.

        Step SELESAI kalau salah satu terjadi lebih dulu:
          - `duration_sec` terlampaui (safety cap), ATAU
          - gerbang terlihat TERUS-MENERUS selama `gate_confirm_sec` (debounce —
            satu frame false-positive YOLO tidak boleh memotong manuver), dan itu
            HANYA dinilai setelah `min_runtime_sec` terlampaui.

        `min_runtime_sec` bukan hiasan: kalau gerbang KEBETULAN sudah terlihat tepat
        saat step dimulai (mis. kapal berhenti tak jauh dari gerbang berikutnya), tanpa
        jeda ini step selesai dalam satu frame dan manuvernya tidak pernah terjadi.

        Variabel step yang dipakai:
          step['steer']            (float) — -1.0 (kiri penuh) .. +1.0 (kanan penuh). Default 0.0
          step['throttle']         (float) — 0.0 .. 1.0. Default 0.3
          step['duration_sec']     (float) — Batas waktu MAKSIMUM (detik). Default 10.0.
                                    0 = tanpa batas waktu — kapal hanya berhenti kalau
                                    gerbang ketemu. HATI-HATI memakainya.
          step['min_runtime_sec']  (float) — Waktu minimum sebelum deteksi gerbang boleh
                                    mengakhiri step. Default 1.5
          step['gate_confirm_sec'] (float) — Lama gerbang harus terlihat kontinu.
                                    Default STEER_GATE_CONFIRM_SEC (0.3)
          step['ignore_area_px2']  (float) — Area bbox minimum agar sebuah bola dihitung.
                                    Default SEQ_IGNORE_AREA_PX2 (ikut skala resolusi).
        """
        steer        = max(-1.0, min(1.0, self._safe_float(step.get("steer"), 0.0)))
        throttle     = max(0.0, min(1.0, self._safe_float(step.get("throttle"), 0.3)))
        duration_sec = self._safe_float(step.get("duration_sec"), 10.0)
        min_runtime  = max(0.0, self._safe_float(step.get("min_runtime_sec"), 1.5))
        confirm_sec  = max(0.0, self._safe_float(step.get("gate_confirm_sec"),
                                                 self.STEER_GATE_CONFIRM_SEC))
        min_area     = self._safe_float(step.get("ignore_area_px2"), self.SEQ_IGNORE_AREA_PX2)

        # Pastikan FC benar-benar di MANUAL tiap frame, bukan cuma sekali saat step
        # dimulai — sama seperti GYRO_FORWARD. Di GUIDED, RC override tidak menggerakkan
        # apa pun dan kapal akan diam sepanjang durasi tanpa gejala yang jelas.
        if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
            print("[MissionEngine] 🔄 Automatic mode switch to MANUAL for STEER_UNTIL_GATE...")
            self.asv.set_mode("MANUAL")

        now = time.time()
        elapsed = now - self._step_start_time

        # --- Selesai karena waktu habis (safety cap) ---
        if duration_sec > 0 and elapsed >= duration_sec:
            print(f"[MissionEngine] ✅ STEER_UNTIL_GATE selesai! Durasi {duration_sec:.1f}s "
                  f"terpenuhi (gerbang tidak ketemu).")
            self._steer_gate_seen_since = None
            self._advance_step()
            return 0.0, 0.0, "STEER_UNTIL_GATE"

        red_seen, green_seen = self._gate_pair_visible(detected_balls, min_area)
        gate_visible = red_seen and green_seen

        # --- Selesai karena GERBANG terkonfirmasi terlihat ---
        if elapsed >= min_runtime:
            if gate_visible:
                if self._steer_gate_seen_since is None:
                    self._steer_gate_seen_since = now
                elif (now - self._steer_gate_seen_since) >= confirm_sec:
                    print(f"[MissionEngine] ✅ STEER_UNTIL_GATE selesai! Gerbang (merah+hijau) "
                          f"terkonfirmasi setelah {elapsed:.1f}s → lanjut step berikutnya.")
                    self._steer_gate_seen_since = None
                    self._advance_step()
                    return 0.0, 0.0, "STEER_UNTIL_GATE"
            else:
                # Salah satu warna hilang → hitungan debounce diulang dari nol.
                self._steer_gate_seen_since = None
        else:
            # Masih dalam masa min_runtime: jangan biarkan hitungan menumpuk diam-diam,
            # supaya debounce benar-benar dimulai dari nol saat penilaian dibuka.
            self._steer_gate_seen_since = None

        remaining = max(0.0, duration_sec - elapsed) if duration_sec > 0 else float("inf")
        rem_label = "∞" if duration_sec <= 0 else f"{remaining:.1f}s"
        dir_label = "←" if steer < -0.05 else ("→" if steer > 0.05 else "↑")
        gate_label = f"[M:{'✓' if red_seen else '-'} H:{'✓' if green_seen else '-'}]"
        if gate_visible and self._steer_gate_seen_since is not None:
            gate_label += f" {now - self._steer_gate_seen_since:.1f}/{confirm_sec:.1f}s"
        elif elapsed < min_runtime:
            gate_label += f" (tunggu {min_runtime - elapsed:.1f}s)"
        label = (f"STEER_UNTIL_GATE {dir_label} | steer={steer:+.2f} thr={throttle:.2f} "
                 f"rem={rem_label} gate={gate_label}")
        return steer, throttle, label

    def _box_visible(self, detected_boxes: Dict, min_area_px2: float) -> Tuple[bool, bool]:
        """
        Apakah BOX terlihat: (biru_terlihat, hijau_terlihat), masing-masing hanya
        dihitung kalau area bounding box-nya >= min_area_px2.

        Dipisah per warna — bukan sekadar "ada box" — supaya label OSD bisa
        menunjukkan warna mana yang sudah ketemu, dan supaya step bisa diminta
        menunggu warna tertentu saja.

        Ambang area WAJIB ada, alasannya sama seperti _gate_pair_visible(): tanpa itu
        satu pantulan air yang lolos YOLO sudah cukup memotong manuver lebih awal.
        """
        def _ada(boxes) -> bool:
            return any(self._bbox_area(b) >= min_area_px2 for b in (boxes or []))

        return _ada(detected_boxes.get(ROLE_BLUE_BOX)), _ada(detected_boxes.get(ROLE_GREEN_BOX))

    def _handle_steer_until_box(self, step: Dict, detected_boxes: Dict
                                ) -> Tuple[float, float, str]:
        """
        Handle STEER_UNTIL_BOX step.

        Kembarannya STEER_UNTIL_GATE, dengan satu perbedaan: yang mengakhiri manuver
        adalah BOX (biru/hijau), bukan gerbang bola. Steer & throttle tetap konstan
        lewat RC override di mode MANUAL, tanpa feedback GPS/kompas.

        Gunanya: setelah lintasan buoy selesai, kapal perlu menyapu ke arah area box.
        Manuver itu harus berhenti begitu box masuk pandangan — bukan setelah durasi
        tetap habis — supaya PHOTO_BOX berikutnya mulai dengan target sudah di frame,
        bukan masih harus mencari dari nol.

        Step SELESAI kalau salah satu terjadi lebih dulu:
          - `duration_sec` terlampaui (safety cap), ATAU
          - box yang diminta terlihat TERUS-MENERUS selama `box_confirm_sec`, dan itu
            HANYA dinilai setelah `min_runtime_sec` terlampaui.

        `min_runtime_sec` sama pentingnya seperti di STEER_UNTIL_GATE: kalau box
        KEBETULAN sudah terlihat tepat saat step dimulai, tanpa jeda ini step selesai
        di frame pertama dan sapuannya tidak pernah terjadi.

        Variabel step yang dipakai:
          step['steer']           (float) — -1.0 (kiri penuh) .. +1.0 (kanan penuh). Default 0.0
          step['throttle']        (float) — 0.0 .. 1.0. Default 0.3
          step['duration_sec']    (float) — Batas waktu MAKSIMUM (detik). Default 10.0.
                                   0 = tanpa batas — kapal hanya berhenti kalau box
                                   ketemu. HATI-HATI memakainya.
          step['target']          (str)   — "any" (default, box mana pun), "blue"/"biru",
                                   "green"/"hijau", atau "both" (dua-duanya sekaligus).
          step['min_runtime_sec'] (float) — Waktu minimum sebelum deteksi box boleh
                                   mengakhiri step. Default 1.5
          step['box_confirm_sec'] (float) — Lama box harus terlihat kontinu.
                                   Default STEER_BOX_CONFIRM_SEC (0.4)
          step['ignore_area_px2'] (float) — Area bbox minimum agar box dihitung, dalam
                                   satuan referensi 1920x1080 (ikut skala resolusi).
        """
        steer        = max(-1.0, min(1.0, self._safe_float(step.get("steer"), 0.0)))
        throttle     = max(0.0, min(1.0, self._safe_float(step.get("throttle"), 0.3)))
        duration_sec = self._safe_float(step.get("duration_sec"), 10.0)
        min_runtime  = max(0.0, self._safe_float(step.get("min_runtime_sec"), 1.5))
        confirm_sec  = max(0.0, self._safe_float(step.get("box_confirm_sec"),
                                                 self.STEER_BOX_CONFIRM_SEC))
        min_area     = self._area_dari_step(step, "ignore_area_px2", self.SEQ_IGNORE_AREA_PX2)

        # Pastikan FC benar-benar di MANUAL tiap frame, bukan cuma sekali saat step
        # dimulai — sama seperti STEER_UNTIL_GATE. Di GUIDED, RC override tidak
        # menggerakkan apa pun dan kapal diam sepanjang durasi tanpa gejala yang jelas.
        if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
            print("[MissionEngine] 🔄 Automatic mode switch to MANUAL for STEER_UNTIL_BOX...")
            self.asv.set_mode("MANUAL")

        now = time.time()
        elapsed = now - self._step_start_time

        # --- Selesai karena waktu habis (safety cap) ---
        if duration_sec > 0 and elapsed >= duration_sec:
            print(f"[MissionEngine] ✅ STEER_UNTIL_BOX selesai! Durasi {duration_sec:.1f}s "
                  f"terpenuhi (box tidak ketemu).")
            self._steer_box_seen_since = None
            self._advance_step()
            return 0.0, 0.0, "STEER_UNTIL_BOX"

        blue_seen, green_seen = self._box_visible(detected_boxes or {}, min_area)
        mode = self._steer_box_target_mode(step)
        if mode == "blue":
            box_visible, target_label = blue_seen, "biru"
        elif mode == "green":
            box_visible, target_label = green_seen, "hijau"
        elif mode == "both":
            box_visible, target_label = (blue_seen and green_seen), "biru+hijau"
        else:
            box_visible, target_label = (blue_seen or green_seen), "box apa pun"

        # --- Selesai karena BOX terkonfirmasi terlihat ---
        if elapsed >= min_runtime:
            if box_visible:
                if self._steer_box_seen_since is None:
                    self._steer_box_seen_since = now
                elif (now - self._steer_box_seen_since) >= confirm_sec:
                    print(f"[MissionEngine] ✅ STEER_UNTIL_BOX selesai! Box ({target_label}) "
                          f"terkonfirmasi setelah {elapsed:.1f}s → lanjut step berikutnya.")
                    self._steer_box_seen_since = None
                    self._advance_step()
                    return 0.0, 0.0, "STEER_UNTIL_BOX"
            else:
                # Box hilang → hitungan debounce diulang dari nol.
                self._steer_box_seen_since = None
        else:
            # Masih dalam masa min_runtime: jangan biarkan hitungan menumpuk diam-diam,
            # supaya debounce benar-benar dimulai dari nol saat penilaian dibuka.
            self._steer_box_seen_since = None

        remaining = max(0.0, duration_sec - elapsed) if duration_sec > 0 else float("inf")
        rem_label = "∞" if duration_sec <= 0 else f"{remaining:.1f}s"
        dir_label = "←" if steer < -0.05 else ("→" if steer > 0.05 else "↑")
        box_label = f"[B:{'✓' if blue_seen else '-'} H:{'✓' if green_seen else '-'}]"
        if box_visible and self._steer_box_seen_since is not None:
            box_label += f" {now - self._steer_box_seen_since:.1f}/{confirm_sec:.1f}s"
        elif elapsed < min_runtime:
            box_label += f" (tunggu {min_runtime - elapsed:.1f}s)"
        label = (f"STEER_UNTIL_BOX {dir_label} | steer={steer:+.2f} thr={throttle:.2f} "
                 f"rem={rem_label} box={box_label}")
        return steer, throttle, label

    # ------------------------------------------------------------------ #
    #  Sequential Buoy Tracking Handlers                                 #
    # ------------------------------------------------------------------ #

    def _handle_buoy_chase(self, step, gate_x: Optional[float], detected_balls: Dict) -> Tuple[float, float, str]:
        """
        Handle BUOY_CHASE step.

        Versi permukaan-konfigurasi SEDERHANA dari SEQUENTIAL_BUOY — TANPA target
        pass_count, hanya 2 field yang bisa diatur operator:
          step['throttle']         (float) — Throttle 0.0-1.0. Opsional, fallback ke
                                    speed_scheduler.max_base_throttle.
          step['ignore_area_px2']  (float) — Bola/pasangan dengan area bbox di bawah
                                    nilai ini ("terlalu jauh") diabaikan total, tidak
                                    dikejar maupun dikunci. Opsional, fallback ke
                                    SEQ_IGNORE_AREA_PX2.
          step['blind_search_timeout_sec'] (float) — Lama kapal tetap BERGERAK saat tidak
                                    ada buoy sama sekali di frame. Lewat durasi ini kapal
                                    BERHENTI (throttle 0), tidak terus melaju buta.
                                    Opsional, fallback ke SEQ_BLIND_SEARCH_TIMEOUT_SEC.
          step['blind_lean_percent'] (float, -100..+100) — Arah & besar miring selama
                                    bergerak buta itu: negatif KIRI, positif KANAN,
                                    0 = lurus (perilaku lama). Lihat _blind_lean_steer().

        Selesai OTOMATIS begitu tidak ada buoy terdeteksi lagi di frame (tidak perlu
        target jumlah pasangan) — sama seperti perilaku default SEQUENTIAL_BUOY saat
        buoy course sudah habis.

        SENGAJA delegasi PENUH ke _handle_sequential_buoy(): mesin gate FSM, safeguard
        pairing (rasio area, lebar maksimum, identity-tracking per-frame), manuver
        TRANSITIONING/single-ball-avoidance, dan safety timeout SEMUA sudah teruji
        lapangan lewat SEQUENTIAL_BUOY — menulis ulang logic yang sama dari nol untuk
        step "sederhana" ini justru RAWAN memperkenalkan bug baru yang sudah pernah
        diperbaiki di sana. State (_seq_*) dan reset-nya SUDAH SAMA (lihat blok mode-
        switch di update_frame() — BUOY_CHASE ikut memicu _reset_sequential_state()).

        Catatan kosmetik: label debug yang di-overlay ke frame kamera (bukan status
        mission utama di UI) akan tetap menyebut "SEQUENTIAL_BUOY" karena berasal dari
        handler yang sama — tidak memengaruhi perilaku kontrol.
        """
        return self._handle_sequential_buoy(step, gate_x, detected_balls)

    def _handle_sequential_buoy(self, step, gate_x: Optional[float], detected_balls: Dict):
        """
        Handle SEQUENTIAL_BUOY step.

        Menavigasi kapal melewati pasangan buoy (hijau + merah) secara berurutan, TANPA
        perlu dikonfigurasi berapa banyak pasangan yang harus dilewati. Pasangan diurutkan
        berdasarkan jarak terdekat ke kamera (bounding box terbesar = terdekat), sehingga
        Pasangan 1 = pasang buoy paling dekat, Pasangan 2 = berikutnya, dst.

        Step SELALU berjalan sampai TIDAK ADA lagi pasangan buoy yang terdeteksi di frame:
        begitu SEARCHING tidak menemukan pasangan valid sama sekali selama
        SEQ_SEARCHING_TIMEOUT_SEC berturut-turut (setelah minimal 1 pasangan berhasil
        dilewati), step dianggap selesai — course dianggap sudah habis. Pasangan yang
        terdeteksi tapi masih terlalu JAUH/kecil untuk DIKUNCI (area bbox <
        SEQ_MIN_PAIR_AREA_PX2) TIDAK langsung di-LOCK, tapi tetap dipakai sebagai target
        approach sementara (steer menuju midpoint-nya) SELAMA sudah lolos safeguard
        rasio-area & lebar-maksimum di _sort_buoy_pairs(). Fallback `gate_x` mentah dari
        tracker (tanpa safeguard apa pun) HANYA dipakai kalau benar-benar tidak ada
        kandidat pasangan yang lolos safeguard sama sekali — sebelumnya kapal langsung
        lompat ke fallback ini begitu pasangan belum cukup besar, yang terbukti di
        lapangan bisa menyeret kapal ke arah salah karena fallback itu tidak dijaga.

        State Machine Dua Level:
          Level 1 — Pair Sequencer : menentukan pasangan mana yang sedang diproses.
          Level 2 — Gate FSM       : SEARCHING → LOCKED → TRANSITIONING → CLEARED → (pair selesai)

        Aturan Sorting (saat SEARCHING):
          _sort_buoy_pairs() mengurutkan pasangan berdasarkan rata-rata area bounding box
          (area terbesar = paling dekat ke kamera). Hanya dipanggil saat state SEARCHING
          untuk menentukan pasangan yang akan dikunci.

        Aturan Gate FSM (saat LOCKED / TRANSITIONING):
          Setelah pasangan dikunci, _sort_buoy_pairs() TIDAK dipanggil lagi.
          Bola yang tersisa dilacak via _find_nearest_ball() terhadap POSISI + AREA
          kunci terakhir (SEQ_AREA_CONTINUITY_MIN_RATIO). Area di-cek karena bola gate
          berikutnya lebih jauh dari kamera → bbox jelas lebih kecil, sehingga tidak bisa
          diambil-alih sebagai identitas bola Pasangan 1 hanya karena kebetulan dekat
          secara piksel. _sort_buoy_pairs() sendiri juga menolak pasangan merah-hijau
          dengan rasio area timpang (SEQ_PAIR_AREA_RATIO_MIN) — mencegah bola sisa
          Pasangan 1 (besar) dipasangkan dengan bola Pasangan 2 (kecil) saat SEARCHING.

        Aturan "Confirmed Hilang" (syarat transisi ke pasangan berikutnya):
          Gate baru dinyatakan CLEARED (unlock Pasangan 1 → siap lock Pasangan 2) jika
          bola tersisa TIDAK terdeteksi selama SEQ_LOST_CONFIRM_SEC secara kontinu
          (debounce, bukan cuma 1 frame miss YOLO). Selama menunggu, steer terakhir yang
          diketahui (last known trajectory + lean paksa) tetap dipertahankan — TIDAK
          pernah dihitung ulang dari bola pasangan lain. SEQ_TRANSITIONING_SAFETY_TIMEOUT_SEC
          hanya jaring pengaman terakhir untuk kasus bola tersisa terus terdeteksi tanpa
          henti (false-positive statis); nilainya sengaja besar agar TIDAK pernah memaksa
          CLEARED saat kapal masih benar-benar melintasi pasangan aktif.

        Aturan transisi lean (arah diambil dari vision/gate_convention.py, BUKAN
        literal kiri/kanan di sini — lihat _lean_steer_for_missing()):
          - Satu bola hilang duluan → kapal condong KE ARAH SISI bola tersebut
          - Kedua bola hilang       → pasangan CLEARED, lanjut ke pasangan berikutnya

        Aturan bola tunggal saat SEARCHING (TIDAK ADA pasangan valid terbentuk —
        entah cuma 1 warna terdeteksi, ATAU dua warna ada tapi gagal lolos safeguard
        rasio-area/lebar-maksimum di sort_ball_pairs, lihat _pick_single_ball_candidate):
        kapal MENJAGA JARAK dari bola itu dengan arah yang ditentukan MURNI oleh
        warna bola (lihat _compute_single_ball_avoid_steer()):
          - Bola penanda tepi KIRI  merangsek ke haluan → kapal didorong ke KANAN
          - Bola penanda tepi KANAN merangsek ke haluan → kapal didorong ke KIRI
          - Bola masih aman di sisinya sendiri            → tidak ada koreksi (0.0)
        Posisi bola relatif terhadap garis tengah frame TIDAK ikut menentukan arah,
        sehingga bola yang menyeberangi garis tengah tidak membalik/melonjakkan
        koreksi — ia justru tetap didorong penuh sampai kembali ke sisinya.

        Format step:
          { "type": "SEQUENTIAL_BUOY", "throttle": 0.4, "ignore_area_px2": 4000,
            "no_detection_finish_sec": 15.0, "single_ball_clearance_px": 384,
            "single_ball_max_steer": 0.4, "transitioning_lean_timeout_sec": 20.0 }

        `throttle` (0.0-1.0) opsional — fallback ke speed_scheduler.max_base_throttle
        jika tidak diisi (lihat _resolve_step_throttle()).

        `ignore_area_px2` (piksel²) opsional — pasangan bola dengan area rata-rata di
        bawah nilai ini dianggap TIDAK ADA sama sekali (bukan cuma "belum boleh dikunci"
        seperti SEQ_MIN_PAIR_AREA_PX2), sehingga tidak dikejar (approach) maupun dikunci.
        Ini yang memungkinkan step SELESAI walau ada deteksi bola yang sangat jauh (mis.
        buoy course lain, noise) — tanpa floor ini, kandidat sejauh apa pun tetap dikejar
        tanpa henti. Fallback ke SEQ_IGNORE_AREA_PX2 jika tidak diisi. Threshold yang SAMA
        ini juga dipakai untuk memfilter kandidat bola TUNGGAL (lihat di bawah) — bola
        tunggal yang lebih kecil dari ini diabaikan sepenuhnya (jatuh ke gate_x/blind).

        `no_detection_finish_sec` (detik) opsional — kalau BENAR-BENAR tidak ada apa pun
        terdeteksi (tidak ada kandidat pasangan SAMA SEKALI, termasuk yang di bawah
        ignore_area_px2, dan tidak ada fallback gate_x) selama durasi ini, step dianggap
        SELESAI (advance ke step berikutnya) — bukan cuma berhenti bergerak seperti
        SEQ_BLIND_SEARCH_TIMEOUT_SEC (5s, tetap berlaku duluan sebagai jaring pengaman
        tabrakan). Berlaku TIDAK PEDULI sudah ada pasangan yang cleared atau belum —
        beda dari SEQ_SEARCHING_TIMEOUT_SEC yang hanya aktif setelah pasangan pertama
        dikunci. Fallback ke SEQ_NO_DETECTION_FINISH_SEC (15.0) jika tidak diisi.

        `single_ball_clearance_px` (piksel) opsional — jarak lateral dari tengah frame
        yang dianggap "aman" dari bola tunggal. Fallback ke SEQ_SINGLE_BALL_CLEARANCE_PX
        (instance-scaled, 384 @ resolusi referensi 1920x1080 — lihat
        _apply_resolution_scaling()) jika tidak diisi.

        `single_ball_max_steer` (0.0-1.0) opsional — steer maksimum koreksi jaga-jarak
        bola tunggal, dicapai saat bola tepat di tengah frame. Fallback ke
        SEQ_SINGLE_BALL_MAX_STEER (0.4) jika tidak diisi.

        `locked_timeout_area_growth_min_ratio` (opsional) — sama seperti TRACKING_BUOY:
        kalau LOCKED timeout (GATE_LOCKED_TIMEOUT_SEC) tercapai TAPI kedua bola masih
        terlihat dan area pasangan sudah membesar sebesar rasio ini sejak lock pertama,
        dihitung sebagai 1 pasangan CLEARED alih-alih reset tanpa hitungan. Fallback ke
        GATE_LOCKED_TIMEOUT_AREA_GROWTH_MIN_RATIO (1.5) jika tidak diisi.

        `transitioning_lean_timeout_sec` (detik) opsional — berapa lama kapal boleh
        mempertahankan manuver condong PAKSA (TRANSITIONING) sebelum jaring pengaman
        terakhir memaksa CLEARED, untuk kasus bola tersisa TERUS terdeteksi tanpa henti
        (mis. false-positive statis) sehingga gate tidak pernah CLEARED lewat jalur
        normal (bola tersisa confirmed hilang). TIDAK memotong manuver condong yang
        masih valid — kapal tetap menahan arah lean sampai bola tersisa BENAR hilang
        ATAU durasi ini terlampaui, mana pun lebih dulu. Fallback ke
        SEQ_TRANSITIONING_SAFETY_TIMEOUT_SEC (20.0) jika tidak diisi.

        `gate_balance_deadband` (rasio 0.0-1.0) opsional — toleransi ketidakseimbangan
        celah kiri-vs-kanan haluan sebelum koreksi menjauh diterapkan di atas steer
        midpoint (lihat _compute_gate_clearance_steer — ini perbaikan untuk kapal yang
        menabrak bola: error midpiksel mutlak tidak bisa membedakan gerbang sempit
        yang berbahaya dari gerbang lebar yang aman). TURUNKAN kalau kapal masih
        menyenggol, NAIKKAN kalau kapal jadi goyah. Fallback ke
        SEQ_GATE_BALANCE_DEADBAND (0.25).

        `gate_max_avoid_steer` (0.0-1.0) opsional — steer maksimum koreksi
        keseimbangan di atas, dicapai saat salah satu bola tepat di garis haluan.
        Fallback ke SEQ_GATE_MAX_AVOID_STEER (0.5).

        `transition_lean_magnitude` (0.0-1.0) opsional — kekuatan condong PAKSA saat
        TRANSITIONING (satu bola hilang, kapal dipaksa condong ke sisi bola yang
        hilang). Naikkan kalau kapal masih menyenggol bola tersisa saat melintas,
        turunkan kalau kapal terlalu membanting keluar jalur. Fallback ke
        TRANSITION_LEAN_MAGNITUDE (0.4). Hanya dipakai kalau handoff di bawah TIDAK
        menemukan gerbang berikutnya (atau dimatikan).

        `transition_use_next_pair` (bool, default TRUE) — saat satu bola gerbang ini
        hilang, bidik gerbang BERIKUTNYA yang masih terlihat utuh alih-alih condong
        buta. Gerbang yang sudah kehilangan satu bola tidak lagi memberi arah yang
        utuh; mengarah ke bola tunggal yang tersisa justru menyeret kapal
        menabraknya. Bola sisa gerbang ini dibuang dulu dari kandidat pairing supaya
        tidak membentuk "gerbang hantu" dengan bola gerbang berikutnya, dan steer ke
        gerbang baru tetap ditambah koreksi jaga-jarak terhadap bola sisa itu (kapal
        masih fisik melintasinya). Set false untuk kembali ke perilaku lama.
        """
        throttle    = self._resolve_step_throttle(step)
        cleared     = self._seq_pairs_cleared
        pair_num    = cleared + 1   # Display: pasangan yang sedang diincar (1-indexed)
        # Kekuatan condong PAKSA saat TRANSITIONING (satu bola hilang) — configurable
        # per-step supaya operator bisa memperkuat kalau kapal masih menyenggol bola,
        # atau memperlemah kalau kapal terlalu membanting keluar jalur.
        lean_magnitude = self._safe_float(
            step.get("transition_lean_magnitude"), self.TRANSITION_LEAN_MAGNITUDE)
        # Noise-floor pasangan. Dihitung di sini (bukan di dalam blok SEARCHING saja)
        # karena TRANSITIONING juga memakainya untuk mencari pasangan BERIKUTNYA.
        ignore_area_px2 = self._safe_float(step.get("ignore_area_px2"), self.SEQ_IGNORE_AREA_PX2)
        # Handoff ke gerbang berikutnya saat satu bola gerbang ini hilang (default ON).
        # Set 0/false untuk kembali ke perilaku lama (condong PAKSA konstan saja).
        use_next_pair = self._safe_bool(step.get("transition_use_next_pair"), True)

        # ── Pastikan mode MANUAL ─────────────────────────────────────────
        if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
            print("[MissionEngine] 🔄 Automatic mode switch to MANUAL for SEQUENTIAL_BUOY...")
            self.asv.set_mode("MANUAL")

        pair_label = f"{pair_num}"

        # ══════════════════════════════════════════════════════════════════
        #  GATE STATE MACHINE (Level 2) — menggunakan _seq_* state vars
        #  DILARANG menggunakan _gate_* vars milik TRACKING_BUOY.
        # ══════════════════════════════════════════════════════════════════

        if self._seq_gate_lock_state == self.GATE_SEARCHING:
            # ── SEARCHING ──────────────────────────────────────────────

            # ── Timeout guard SEARCHING → deteksi "tidak ada bola lagi" ─
            # Satu-satunya cara step ini tahu kapan harus berhenti: begitu terlalu lama
            # di SEARCHING tanpa pasangan valid terdeteksi, buoy dianggap sudah habis dan
            # step SELESAI otomatis. Timer hanya aktif setelah minimal 1 pasangan cleared
            # (self._seq_pairs_cleared > 0) agar tidak memotong waktu approach ke pasangan
            # pertama.
            if (self._seq_pairs_cleared > 0
                    and self._seq_gate_state_entered_at > 0):
                searching_elapsed = time.time() - self._seq_gate_state_entered_at
                if searching_elapsed > self.SEQ_SEARCHING_TIMEOUT_SEC:
                    print(f"[SEQ_BUOY] ✅ Tidak ada pasangan buoy baru terdeteksi selama "
                          f"{searching_elapsed:.1f}s setelah {cleared} pasangan dilewati → "
                          f"anggap SEQUENTIAL_BUOY selesai (buoy habis).")
                    self._reset_sequential_state()
                    self._advance_step()
                    return 0.0, 0.0, "SEQUENTIAL_BUOY"

            # Buang dulu bola yang dekat posisi pasangan yang BARU SAJA CLEARED
            # (zona larangan sementara, lihat _filter_recently_cleared) sebelum pairing.
            searchable_balls = self._filter_recently_cleared(detected_balls)

            # Sort HANYA di state SEARCHING untuk menentukan pasangan target.
            # Pasangan[0] = pasangan terdekat (area rata-rata bounding box terbesar).
            raw_pairs = self._sort_buoy_pairs(searchable_balls)

            # ── Ignore-floor: buang pasangan yang area rata-ratanya < ignore_area_px2
            # SEBELUM dipakai sebagai kandidat LOCK *atau* APPROACH (lihat
            # SEQ_IGNORE_AREA_PX2). Tanpa ini, pasangan sekecil/sejauh apa pun tetap
            # dikejar tanpa henti selama masih lolos safeguard rasio-area/lebar-
            # maksimum — kapal tidak akan pernah menyimpulkan "buoy sudah habis" kalau
            # yang terdeteksi cuma objek jauh yang tidak akan pernah cukup besar untuk
            # di-LOCK. Opsional per-step (dihitung sekali di awal handler ini).
            pairs = [
                (r, g) for (r, g) in raw_pairs
                if self._pair_avg_area(r, g) >= ignore_area_px2
            ]

            target_pair = pairs[0] if pairs else None

            # ── Area Filter: abaikan pasangan yang terlalu jauh/kecil untuk DIKUNCI ──
            # Jika rata-rata area bounding box kedua bola < SEQ_MIN_PAIR_AREA_PX2,
            # bola dianggap terlalu jauh (bukan target LOCK valid, tapi masih boleh
            # jadi target APPROACH — beda dari ignore-floor di atas yang membuang
            # pasangan sepenuhnya). Kapal terus maju tanpa mengunci, sehingga tidak
            # salah jalan ke bola yang sudah lewat atau bola dari misi lain.
            if target_pair is not None:
                avg_area = self._pair_avg_area(*target_pair)
                if avg_area < self.SEQ_MIN_PAIR_AREA_PX2:
                    target_pair = None  # bola terlalu jauh untuk dikunci → tetap approach saja

            red_ball   = target_pair[0] if target_pair else None
            green_ball = target_pair[1] if target_pair else None
            red_visible   = red_ball is not None
            green_visible = green_ball is not None

            if red_visible and green_visible:
                # Kedua bola terlihat & area cukup besar → LOCK pasangan terdekat
                self._seq_locked_red_pos   = (red_ball[0],   red_ball[1])
                self._seq_locked_green_pos = (green_ball[0], green_ball[1])
                self._seq_locked_red_area   = self._bbox_area(red_ball)
                self._seq_locked_green_area = self._bbox_area(green_ball)
                self._seq_locked_entry_area = self._pair_avg_area(red_ball, green_ball)
                self._seq_gate_lock_state  = self.GATE_LOCKED
                self._seq_gate_state_entered_at = time.time()
                self._seq_missing_lost_since = None
                self._seq_blind_search_since = None
                print(f"[SEQ_GATE] SEARCHING → LOCKED "
                      f"(pair {pair_label}, red={self._seq_locked_red_pos}, "
                      f"green={self._seq_locked_green_pos})")
                locked_mid_x = (self._seq_locked_red_pos[0] + self._seq_locked_green_pos[0]) // 2
                steer = self.tracking_controller.compute_normalized_steering(locked_mid_x)
                # Clearance guard: jaga jarak per-BOLA, bukan cuma midpoint (lihat
                # _compute_gate_clearance_steer — ini yang mencegah kapal menabrak
                # bola saat midpoint sudah "pas tengah" tapi salah satu bola nyaris
                # di garis haluan).
                steer = max(-1.0, min(1.0, steer + self._compute_gate_clearance_steer(
                    self._seq_locked_red_pos[0], self._seq_locked_green_pos[0], step)))
                label = f"SEQ_GATE:LOCKED | SEQUENTIAL_BUOY (pair {pair_label})"
                return steer, throttle, label
            else:
                # Belum cukup besar/dekat untuk DIKUNCI, TAPI `pairs` (sudah lolos
                # safeguard rasio-area/lebar-maksimum DAN ignore-floor di atas — cuma
                # belum lolos SEQ_MIN_PAIR_AREA_PX2, masih agak jauh) mungkin masih
                # berisi kandidat yang layak DIKEJAR (approach). PRIORITASKAN kandidat
                # aman ini, JANGAN langsung lompat ke `gate_x` mentah dari tracker (itu
                # TIDAK punya pengaman rasio-area/lebar-maksimum sama sekali, sehingga
                # bisa menyambungkan bola dari gate yang salah dan menyeret kapal ke
                # arah yang keliru saat SEARCHING berlangsung lama — ini yang terjadi &
                # diamati langsung di lapangan).
                if pairs:
                    # Ada sinyal (kandidat aman atau fallback kasar) → reset timer "buta".
                    self._seq_blind_search_since = None
                    approach_r, approach_g = pairs[0]
                    approach_mid_x = (approach_r[0] + approach_g[0]) // 2
                    steer = self.tracking_controller.compute_normalized_steering(approach_mid_x)
                    label = f"SEQ_GATE:SEARCHING (approaching) | SEQUENTIAL_BUOY (pair {pair_label})"
                    return steer, throttle, label

                # ── TIDAK ADA pasangan valid terbentuk (pairing gagal total, bukan cuma
                # "terlalu jauh untuk dikunci") → JAGA JARAK dari bola individu terbesar
                # yang ada, jangan mengejarnya. Berlaku baik saat cuma 1 warna yang
                # terdeteksi MAUPUN saat kedua warna ada tapi tidak lolos safeguard
                # rasio-area/lebar-maksimum (lihat _pick_single_ball_candidate). Prioritaskan
                # ini di atas gate_x mentah — gate_x adalah offset TETAP dari posisi bola
                # yang diumpankan ke PID steering yang sama dengan target pasangan, sehingga
                # kapal tetap "mengikuti" bola itu setiap kali ia bergerak (persis masalah
                # yang dilaporkan). Reuse ignore_area_px2 yang sama dengan filter pasangan
                # di atas — bola yang lebih kecil dari itu diabaikan sepenuhnya (jatuh ke
                # gate_x/blind di bawah).
                single = self._pick_single_ball_candidate(searchable_balls, ignore_area_px2)
                if single is not None:
                    ball, color = single
                    self._seq_blind_search_since = None
                    steer = self._compute_single_ball_avoid_steer(ball, color, step)
                    label = (f"SEQ_GATE:SEARCHING (single {color} @{ball[0]}px "
                             f"sisi-{side_of(color)}) steer={steer:+.2f} "
                             f"| SEQUENTIAL_BUOY (pair {pair_label})")
                    return steer, throttle, label
                elif gate_x is not None:
                    # Tidak ada kandidat pasangan MAUPUN bola tunggal yang aman sama
                    # sekali → fallback visual dari tracker (kasar, tanpa safeguard,
                    # tapi lebih baik daripada diam total).
                    self._seq_blind_search_since = None
                    steer = self.tracking_controller.compute_normalized_steering(gate_x)
                    label = f"SEQ_GATE:SEARCHING | SEQUENTIAL_BUOY (pair {pair_label})"
                    return steer, throttle, label
                else:
                    # Tidak ada target SAMA SEKALI (tidak ada kandidat, tidak ada gate_x).
                    # Beri jeda singkat maju lurus (SEQ_BLIND_SEARCH_TIMEOUT_SEC) agar
                    # buoy sempat masuk kembali ke frame kalau memang cuma sesaat hilang.
                    # SETELAH itu, STOP majunya (throttle=0) — JANGAN terus maju buta
                    # tanpa batas waktu. Sebelumnya kapal bisa maju lurus TERUS-MENERUS
                    # tanpa henti saat tidak ada bola sama sekali di frame, sampai
                    # menabrak tembok atau keluar arena (ditemukan & dikonfirmasi
                    # langsung di lapangan).
                    now = time.time()
                    if self._seq_blind_search_since is None:
                        self._seq_blind_search_since = now
                    blind_duration = now - self._seq_blind_search_since

                    # ── Selesaikan step kalau "buta total" berlarut-larut ───
                    # Beda dari SEQ_SEARCHING_TIMEOUT_SEC (HANYA aktif setelah pasangan
                    # pertama di-cleared), guard ini berlaku dari awal step — mengisi
                    # celah kasus tidak ada bola terdeteksi SAMA SEKALI sejak awal
                    # (kamera belum menghadap buoy, atau course memang sudah kosong).
                    no_detection_finish_sec = self._safe_float(
                        step.get("no_detection_finish_sec"), self.SEQ_NO_DETECTION_FINISH_SEC)
                    if blind_duration > no_detection_finish_sec:
                        print(f"[SEQ_BUOY] ✅ Buta total selama {blind_duration:.1f}s (tidak ada "
                              f"kandidat/gate_x sama sekali) → anggap SEQUENTIAL_BUOY selesai "
                              f"(tidak ada buoy terdeteksi).")
                        self._reset_sequential_state()
                        self._advance_step()
                        return 0.0, 0.0, "SEQUENTIAL_BUOY"

                    # Lama & arah gerak saat "buta" kini bisa diatur per-step.
                    # Sebelumnya durasinya HARDCODED 5 detik dan arahnya selalu lurus,
                    # sehingga operator tidak punya cara menyusul lintasan yang membelok
                    # setelah buoy habis dari pandangan.
                    blind_timeout = self._safe_float(
                        step.get("blind_search_timeout_sec"), self.SEQ_BLIND_SEARCH_TIMEOUT_SEC)
                    blind_steer = self._blind_lean_steer(step)

                    if blind_duration > blind_timeout:
                        label = (f"SEQ_GATE:SEARCHING (blind {blind_duration:.1f}s, HOLD) "
                                 f"| SEQUENTIAL_BUOY (pair {pair_label})")
                        return 0.0, 0.0, label
                    lean_tag = f", miring {blind_steer * 100:+.0f}%" if blind_steer else ""
                    label = (f"SEQ_GATE:SEARCHING (no target{lean_tag}) "
                             f"| SEQUENTIAL_BUOY (pair {pair_label})")
                    return blind_steer, throttle, label

        elif self._seq_gate_lock_state == self.GATE_LOCKED:
            # ── LOCKED ─────────────────────────────────────────────────
            # Jangan panggil _sort_buoy_pairs() di sini.
            # Gunakan _find_nearest_ball() terhadap posisi & AREA kunci terakhir agar
            # bola dari pasangan berikutnya (lebih jauh → bbox lebih kecil) yang masuk
            # frame TIDAK diambil-alih sebagai identitas bola Pasangan 1 yang sedang dikunci.
            nearest_red   = self._find_nearest_ball(
                detected_balls.get("red",   []), self._seq_locked_red_pos,
                self._seq_locked_red_area, self.SEQ_AREA_CONTINUITY_MIN_RATIO,
                max_dist_px=self.SEQ_IDENTITY_MAX_DIST_PX)
            nearest_green = self._find_nearest_ball(
                detected_balls.get("green", []), self._seq_locked_green_pos,
                self._seq_locked_green_area, self.SEQ_AREA_CONTINUITY_MIN_RATIO,
                max_dist_px=self.SEQ_IDENTITY_MAX_DIST_PX)

            red_visible_locked   = nearest_red   is not None
            green_visible_locked = nearest_green is not None

            # ── Timeout guard: terlalu lama LOCKED tanpa bola hilang → kembali SEARCHING
            # KECUALI area pasangan sudah membesar signifikan sejak lock pertama kali —
            # bukti kapal BENAR mendekat, bukan cuma diam. Sama seperti TRACKING_BUOY,
            # lihat GATE_LOCKED_TIMEOUT_AREA_GROWTH_MIN_RATIO.
            now = time.time()
            locked_duration = now - self._seq_gate_state_entered_at
            if locked_duration > self.GATE_LOCKED_TIMEOUT_SEC and red_visible_locked and green_visible_locked:
                growth_ratio = self._safe_float(
                    step.get("locked_timeout_area_growth_min_ratio"),
                    self.GATE_LOCKED_TIMEOUT_AREA_GROWTH_MIN_RATIO)
                current_area = self._pair_avg_area(nearest_red, nearest_green)
                area_grew_enough = (
                    self._seq_locked_entry_area is not None and self._seq_locked_entry_area > 0
                    and current_area >= self._seq_locked_entry_area * growth_ratio
                )
                if area_grew_enough:
                    print(f"[SEQ_GATE] LOCKED TIMEOUT ({locked_duration:.1f}s) TAPI area membesar "
                          f"{current_area:.0f}px² (dari {self._seq_locked_entry_area:.0f}px² saat lock, "
                          f"rasio {current_area / self._seq_locked_entry_area:.2f}x, pair {pair_label}) → "
                          f"anggap SUDAH LEWAT, hitung sebagai pass.")
                    self._seq_gate_lock_state = self.GATE_CLEARED
                    return self._handle_seq_gate_cleared(pair_num)
                else:
                    entry_area_label = f"{self._seq_locked_entry_area:.0f}" if self._seq_locked_entry_area else "?"
                    print(f"[SEQ_GATE] LOCKED TIMEOUT ({locked_duration:.1f}s), area TIDAK membesar cukup "
                          f"({current_area:.0f}px² vs {entry_area_label}px² saat lock, pair {pair_label}) → "
                          f"SEARCHING (reset, bukan pass valid).")
                    self._reset_sequential_gate_fsm()
                    label = f"SEQ_GATE:SEARCHING (timeout) | SEQUENTIAL_BUOY (pair {pair_label})"
                    return 0.0, throttle, label

            if red_visible_locked and green_visible_locked:
                # Kedua bola masih terlihat → update posisi + area locked pair & PID ke midpoint
                self._seq_locked_red_pos   = (nearest_red[0],   nearest_red[1])
                self._seq_locked_green_pos = (nearest_green[0], nearest_green[1])
                self._seq_locked_red_area   = self._bbox_area(nearest_red)
                self._seq_locked_green_area = self._bbox_area(nearest_green)
                locked_mid_x = (self._seq_locked_red_pos[0] + self._seq_locked_green_pos[0]) // 2
                steer = self.tracking_controller.compute_normalized_steering(locked_mid_x)
                # Clearance guard per-BOLA di atas steer midpoint (lihat
                # _compute_gate_clearance_steer). Ini jalur yang paling sering aktif
                # saat kapal benar-benar melintasi gerbang.
                clearance_steer = self._compute_gate_clearance_steer(
                    self._seq_locked_red_pos[0], self._seq_locked_green_pos[0], step)
                steer = max(-1.0, min(1.0, steer + clearance_steer))
                clearance_tag = f" avoid={clearance_steer:+.2f}" if abs(clearance_steer) > 0.01 else ""
                label = f"SEQ_GATE:LOCKED{clearance_tag} | SEQUENTIAL_BUOY (pair {pair_label})"
                return steer, throttle, label

            elif not red_visible_locked and green_visible_locked:
                # ★ Bola MERAH hilang duluan → condong ke SISI MERAH (lihat konvensi)
                self._seq_missing_color     = "red"
                self._seq_gate_lock_state   = self.GATE_TRANSITIONING
                self._seq_gate_state_entered_at = time.time()
                self._seq_missing_lost_since = None  # bola hijau tersisa baru saja, belum "hilang"
                self._seq_locked_green_pos  = (nearest_green[0], nearest_green[1])
                self._seq_locked_green_area = self._bbox_area(nearest_green)
                # Steer PAKSA konstan — pertahankan sampai bola hijau juga hilang.
                self._seq_transition_steer = self._lean_steer_for_missing("red", lean_magnitude)
                print(f"[SEQ_GATE] LOCKED → TRANSITIONING "
                      f"(pair {pair_label}, missing=red/{side_of('red').upper()}, "
                      f"lean={self._seq_transition_steer:+.2f})")
                label = (f"SEQ_GATE:TRANSITIONING({self._lean_arrow('red')}) "
                         f"| SEQUENTIAL_BUOY (pair {pair_label})")
                return self._seq_transition_steer, throttle, label

            elif red_visible_locked and not green_visible_locked:
                # ★ Bola HIJAU hilang duluan → condong ke SISI HIJAU (lihat konvensi)
                self._seq_missing_color     = "green"
                self._seq_gate_lock_state   = self.GATE_TRANSITIONING
                self._seq_gate_state_entered_at = time.time()
                self._seq_missing_lost_since = None  # bola merah tersisa baru saja, belum "hilang"
                self._seq_locked_red_pos    = (nearest_red[0], nearest_red[1])
                self._seq_locked_red_area   = self._bbox_area(nearest_red)
                # Steer PAKSA konstan — pertahankan sampai bola merah juga hilang.
                self._seq_transition_steer = self._lean_steer_for_missing("green", lean_magnitude)
                print(f"[SEQ_GATE] LOCKED → TRANSITIONING "
                      f"(pair {pair_label}, missing=green/{side_of('green').upper()}, "
                      f"lean={self._seq_transition_steer:+.2f})")
                label = (f"SEQ_GATE:TRANSITIONING({self._lean_arrow('green')}) "
                         f"| SEQUENTIAL_BUOY (pair {pair_label})")
                return self._seq_transition_steer, throttle, label

            else:
                # Kedua bola hilang sekaligus dari LOCKED → langsung CLEARED
                self._seq_gate_lock_state = self.GATE_CLEARED
                print(f"[SEQ_GATE] LOCKED → CLEARED (pair {pair_label}, kedua bola hilang bersamaan)")
                return self._handle_seq_gate_cleared(pair_num)

        elif self._seq_gate_lock_state == self.GATE_TRANSITIONING:
            # ── TRANSITIONING ──────────────────────────────────────────
            # Tunggu bola TERSISA (bukan yang hilang) juga confirmed hilang dari frame,
            # dengan debounce SEQ_LOST_CONFIRM_SEC (satu frame miss deteksi YOLO tidak
            # langsung dianggap "hilang" — mencegah CLEARED prematur yang bisa membuka
            # celah salah pasang dengan gate berikutnya di SEARCHING).
            # DILARANG KERAS memperhitungkan bola dari pasangan berikutnya — pakai
            # _find_nearest_ball() dengan area-gating agar identitas bola tetap terjaga.
            now = time.time()
            remaining_found_this_frame = False
            remaining_ball = None   # bola sisa gerbang ini (untuk handoff & jaga jarak)
            remaining_color = None  # "red"/"green" — sisinya diturunkan dari warna ini

            if self._seq_missing_color == "red":
                # Bola merah sudah hilang → tunggu bola hijau juga hilang
                nearest_green = self._find_nearest_ball(
                    detected_balls.get("green", []), self._seq_locked_green_pos,
                    self._seq_locked_green_area, self.SEQ_AREA_CONTINUITY_MIN_RATIO,
                    max_dist_px=self.SEQ_IDENTITY_MAX_DIST_PX)
                if nearest_green:
                    remaining_found_this_frame = True
                    remaining_ball, remaining_color = nearest_green, "green"
                    self._seq_locked_green_pos = (nearest_green[0], nearest_green[1])
                    self._seq_locked_green_area = self._bbox_area(nearest_green)
                    # Steer tetap PAKSA konstan selama bola hijau masih terlihat.
                    self._seq_transition_steer = self._lean_steer_for_missing("red", lean_magnitude)

            elif self._seq_missing_color == "green":
                # Bola hijau sudah hilang → tunggu bola merah juga hilang
                nearest_red = self._find_nearest_ball(
                    detected_balls.get("red", []), self._seq_locked_red_pos,
                    self._seq_locked_red_area, self.SEQ_AREA_CONTINUITY_MIN_RATIO,
                    max_dist_px=self.SEQ_IDENTITY_MAX_DIST_PX)
                if nearest_red:
                    remaining_found_this_frame = True
                    remaining_ball, remaining_color = nearest_red, "red"
                    self._seq_locked_red_pos = (nearest_red[0], nearest_red[1])
                    self._seq_locked_red_area = self._bbox_area(nearest_red)
                    # Steer tetap PAKSA konstan selama bola merah masih terlihat.
                    self._seq_transition_steer = self._lean_steer_for_missing("green", lean_magnitude)

            # ── Debounce "confirmed hilang" ────────────────────────────
            if remaining_found_this_frame:
                self._seq_missing_lost_since = None
            elif self._seq_missing_lost_since is None:
                self._seq_missing_lost_since = now

            confirmed_lost = (
                not remaining_found_this_frame
                and self._seq_missing_lost_since is not None
                and (now - self._seq_missing_lost_since) >= self.SEQ_LOST_CONFIRM_SEC
            )

            if confirmed_lost:
                # Bola terakhir sudah TERKONFIRMASI hilang (bukan sekadar 1 frame miss)
                # → pasangan CLEARED. Baru sekarang boleh unlock Pasangan 1 dan
                # menjadikan Pasangan 2 target baru (syarat transisi terpenuhi).
                self._seq_gate_lock_state = self.GATE_CLEARED
                print(f"[SEQ_GATE] TRANSITIONING → CLEARED "
                      f"(pair {pair_label}, bola terakhir confirmed hilang)")
                return self._handle_seq_gate_cleared(pair_num)

            # ── Safety-net timeout ──────────────────────────────────────
            # HANYA jaring pengaman terakhir untuk kasus bola tersisa TERUS terdeteksi
            # tanpa henti (mis. false-positive statis) sehingga gate tidak pernah CLEARED
            # secara normal. Durasinya sengaja jauh lebih besar dari waktu lintas gate
            # normal — TIDAK memaksa CLEARED saat kapal masih benar-benar melintasi
            # pasangan aktif (sesuai aturan: unlock hanya jika kedua bola confirmed hilang).
            # Configurable per-step (transitioning_lean_timeout_sec) supaya operator bisa
            # menentukan sendiri berapa lama kapal boleh menahan manuver condong paksa.
            transitioning_timeout = self._safe_float(
                step.get("transitioning_lean_timeout_sec"), self.SEQ_TRANSITIONING_SAFETY_TIMEOUT_SEC)
            transitioning_duration = now - self._seq_gate_state_entered_at
            if transitioning_duration > transitioning_timeout:
                print(f"[SEQ_GATE] ⚠️ TRANSITIONING SAFETY TIMEOUT ({transitioning_duration:.1f}s) "
                      f"→ CLEARED (pair {pair_label}, paksa — bola tersisa tak kunjung hilang)")
                self._seq_gate_lock_state = self.GATE_CLEARED
                return self._handle_seq_gate_cleared(pair_num)

            # ── HANDOFF ke gerbang BERIKUTNYA ──────────────────────────
            # CATATAN alur: frame PERTAMA saat sebuah bola hilang masih di-return
            # dari blok LOCKED di atas (condong PAKSA), jadi handoff baru aktif mulai
            # frame BERIKUTNYA. Jeda 1 frame (~67ms @15fps) ini disengaja dibiarkan —
            # tidak signifikan secara fisik, dan mempertahankan jalur masuk
            # TRANSITIONING yang sudah teruji lapangan apa adanya.
            # Begitu satu bola gerbang ini hilang, gerbang ini tidak lagi memberi
            # target arah yang utuh — yang tersisa cuma satu bola, dan mengarah ke
            # bola tunggal itu justru menyeret kapal MENABRAKNYA. Alih-alih condong
            # buta, bidik gerbang BERIKUTNYA yang masih utuh terlihat (ide operator:
            # "kalau jumlah bola jadi ganjil, ambil gerbang di belakangnya").
            #
            # Dua pengaman yang tetap dipertahankan:
            #   1. Bola sisa gerbang ini DIBUANG dari kandidat pairing
            #      (_find_next_pair_excluding) supaya tidak membentuk gerbang hantu.
            #   2. Steer ke gerbang berikutnya TETAP ditambah koreksi JAGA JARAK
            #      terhadap bola sisa gerbang ini — kapal masih fisik melintasinya,
            #      jadi tidak boleh membelok ke arahnya demi mengejar gerbang baru.
            if remaining_found_this_frame and remaining_ball is not None and use_next_pair:
                next_pair = self._find_next_pair_excluding(
                    detected_balls, remaining_color, remaining_ball, ignore_area_px2)
                if next_pair is not None:
                    nxt_red, nxt_green = next_pair
                    nxt_mid_x = (nxt_red[0] + nxt_green[0]) // 2
                    steer = self.tracking_controller.compute_normalized_steering(nxt_mid_x)
                    steer += self._compute_gate_clearance_steer(nxt_red[0], nxt_green[0], step)
                    avoid = self._compute_single_ball_avoid_steer(remaining_ball, remaining_color, step)
                    steer = max(-1.0, min(1.0, steer + avoid))
                    label = (f"SEQ_GATE:TRANSITIONING(→next gate) steer={steer:+.2f} "
                             f"avoid={avoid:+.2f} | SEQUENTIAL_BUOY (pair {pair_label})")
                    return steer, throttle, label

            # Tidak ada gerbang berikutnya yang terlihat (atau handoff dimatikan) →
            # pertahankan manuver condong PAKSA / last-known trajectory seperti semula.
            lean_dir = self._lean_arrow(self._seq_missing_color)
            label = (f"SEQ_GATE:TRANSITIONING({lean_dir}) "
                     f"steer={self._seq_transition_steer:+.2f} "
                     f"| SEQUENTIAL_BUOY (pair {pair_label})")
            return self._seq_transition_steer, throttle, label

        # Fallback safety
        return 0.0, 0.0, f"SEQ_GATE:UNKNOWN | SEQUENTIAL_BUOY (pair {pair_label})"

    def _handle_seq_gate_cleared(self, pair_num: int) -> Tuple[float, float, str]:
        """
        Dipanggil saat satu pasangan gate dinyatakan CLEARED.
        Increment cleared counter, reset gate FSM level-2, siap untuk pasangan berikutnya.
        Step tidak pernah selesai dari sini — hanya berhenti saat SEARCHING tidak
        menemukan pasangan lagi (lihat blok SEARCHING di _handle_sequential_buoy).
        """
        self._seq_pairs_cleared += 1
        new_cleared = self._seq_pairs_cleared

        print(f"[SEQ_GATE] 🏁 Pair {pair_num} CLEARED! ({new_cleared} pasangan dilewati)")
        self._broadcast_status()

        # Simpan posisi terakhir pasangan yang baru CLEARED SEBELUM di-reset, sebagai
        # "zona larangan" sementara untuk SEARCHING berikutnya (lihat _filter_recently_cleared).
        self._seq_recently_cleared_red_pos   = self._seq_locked_red_pos
        self._seq_recently_cleared_green_pos = self._seq_locked_green_pos
        self._seq_recently_cleared_at        = time.time()

        self._reset_sequential_gate_fsm()  # Reset gate FSM, tapi PERTAHANKAN pair counter

        next_pair = new_cleared + 1
        print(f"[SEQ_GATE] CLEARED → SEARCHING (siap mengincar pasangan {next_pair})")

        label = f"SEQ_GATE:CLEARED ✅ | SEQUENTIAL_BUOY (pair {pair_num})"
        # Berhenti sejenak agar tidak langsung menabrak pasangan berikutnya
        return 0.0, 0.0, label

    def _sort_buoy_pairs(self, detected_balls: Dict) -> List[Tuple]:
        """
        Mengurutkan buoy yang terdeteksi menjadi pasangan (merah, hijau) berdasarkan
        estimasi jarak terdekat dari kamera (area bounding box terbesar = paling dekat).

        Delegasi ke vision.ball_pairing.sort_ball_pairs() — lihat vision/ball_pairing.py
        untuk detail algoritma pairing (rasio area + jarak piksel maksimum).

        Returns:
            List of (red_ball, green_ball) — max 3 pasangan, urut dari terdekat ke terjauh.
            Setiap elemen adalah tuple (cx, cy, x1, y1, x2, y2).
        """
        raw_red   = list(detected_balls.get("red",   []))
        raw_green = list(detected_balls.get("green", []))
        return sort_ball_pairs(
            raw_red, raw_green,
            min_area_ratio=self.SEQ_PAIR_AREA_RATIO_MIN,
            max_pairs=3,
            max_pair_width_px=self.SEQ_MAX_PAIR_WIDTH_PX,
        )

    def _filter_recently_cleared(self, detected_balls: Dict) -> Dict:
        """
        Buang bola yang terdeteksi dekat posisi terakhir pasangan yang BARU SAJA
        CLEARED (dalam SEQ_CLEARED_EXCLUSION_SEC terakhir), sebelum diberikan ke
        _sort_buoy_pairs() saat SEARCHING.

        Kenapa perlu: begitu FSM kembali ke SEARCHING, _sort_buoy_pairs() mem-pairing
        ULANG dari nol tanpa memori — jika ada residual/ghost detection dari gate yang
        BARU dilewati (atau bola gate berikutnya kebetulan sangat dekat secara piksel
        di arena yang melengkung), ia bisa langsung ke-pairing salah dengan bola gate
        berikutnya pada frame PERTAMA setelah CLEARED. Zona larangan sementara ini
        memberi jeda singkat agar kapal benar-benar bergerak menjauh dari posisi lama
        sebelum area itu diikutsertakan lagi sebagai kandidat pairing.

        Setelah SEQ_CLEARED_EXCLUSION_SEC berlalu, filter ini tidak berpengaruh
        (mengembalikan detected_balls apa adanya).
        """
        if (self._seq_recently_cleared_at <= 0
                or (time.time() - self._seq_recently_cleared_at) > self.SEQ_CLEARED_EXCLUSION_SEC):
            return detected_balls

        def _far_enough(ball: Tuple, excluded_pos: Optional[Tuple[int, int]]) -> bool:
            if excluded_pos is None:
                return True
            dist = math.hypot(ball[0] - excluded_pos[0], ball[1] - excluded_pos[1])
            return dist > self.SEQ_CLEARED_EXCLUSION_RADIUS_PX

        filtered_red = [
            b for b in detected_balls.get("red", [])
            if _far_enough(b, self._seq_recently_cleared_red_pos)
        ]
        filtered_green = [
            b for b in detected_balls.get("green", [])
            if _far_enough(b, self._seq_recently_cleared_green_pos)
        ]
        return {"red": filtered_red, "green": filtered_green}

    def _reset_sequential_gate_fsm(self):
        """
        Reset HANYA gate FSM Sequential Buoy (Level 2) ke SEARCHING.
        TIDAK mereset pair counter (_seq_pairs_cleared).
        Gunakan saat satu pasangan selesai dan siap mengincar pasangan berikutnya.

        _seq_gate_state_entered_at di-set ke time.time() agar SEARCHING timeout
        dapat mulai dihitung segera setelah transisi ke SEARCHING.
        """
        self._seq_gate_lock_state       = self.GATE_SEARCHING
        self._seq_locked_red_pos        = None
        self._seq_locked_green_pos      = None
        self._seq_locked_red_area       = None
        self._seq_locked_green_area     = None
        self._seq_locked_entry_area     = None
        self._seq_missing_color         = None
        self._seq_transition_steer      = 0.0
        self._seq_gate_state_entered_at = time.time()  # mulai timer SEARCHING timeout
        self._seq_gate_pause_start      = 0.0
        self._seq_missing_lost_since    = None
        self._seq_blind_search_since    = None

    def _reset_sequential_state(self):
        """
        Reset SEMUA state Sequential Buoy termasuk pair counter.
        Gunakan saat mission dimulai, di-load, atau di-reset dari awal.
        """
        self._seq_pairs_cleared = 0
        self._reset_sequential_gate_fsm()
        # Reset zona larangan "recently cleared" — TIDAK direset oleh
        # _reset_sequential_gate_fsm() (lihat komentar di __init__), harus
        # dibersihkan eksplisit di sini agar tidak ada residu antar-mission.
        self._seq_recently_cleared_red_pos   = None
        self._seq_recently_cleared_green_pos = None
        self._seq_recently_cleared_at        = 0.0

    @staticmethod
    def _angular_diff(current_deg: float, target_deg: float) -> float:
        """
        Hitung selisih angular antara dua heading (0-360°) dalam range -180..+180.

        Positif = target ada di kanan (perlu belok CW).
        Negatif = target ada di kiri (perlu belok CCW).

        Contoh:
          current=350°, target=10° → diff=+20° (belok kanan 20°)
          current=10°, target=350° → diff=-20° (belok kiri 20°)
        """
        diff = (target_deg - current_deg + 540.0) % 360.0 - 180.0
        return diff

    # ------------------------------------------------------------------ #
    #  Resolution Scaling                                                 #
    # ------------------------------------------------------------------ #

    def set_camera_resolution(self, camera_width: int, camera_height: int):
        """
        API publik untuk mengubah resolusi kamera SETELAH engine sudah dibuat (mis.
        saat konfigurasi resolusi difetch dari DB async setelah __init__ dipanggil).
        Aman dipanggil berkali-kali — selalu menskalakan ULANG dari nilai REFERENSI
        class (1920x1080), bukan dari hasil skala sebelumnya, jadi tidak ada resiko
        "double-scaling" kalau dipanggil lebih dari sekali.

        CATATAN: ini HANYA mengubah threshold piksel di MissionEngine. Resolusi
        capture kamera fisik (cv2.VideoCapture) & TrackingController.frame_width
        HARUS diset terpisah saat konstruksi (lihat main.py) — mengubah resolusi
        capture kamera yang SEDANG BERJALAN butuh re-inisialisasi hardware yang
        jauh lebih berisiko, jadi SENGAJA tidak dicoba di sini.
        """
        self._apply_resolution_scaling(camera_width, camera_height)
        print(f"[MissionEngine] 📐 Resolusi kamera diperbarui → threshold piksel "
              f"diskalakan ulang untuk {self.camera_width}x{self.camera_height}.")

    def _apply_resolution_scaling(self, camera_width: int, camera_height: int):
        """
        Skalakan semua threshold berbasis piksel dari resolusi REFERENSI (1920x1080,
        tempat nilainya dikalibrasi & didokumentasikan — lihat REFERENCE_FRAME_WIDTH/
        HEIGHT) ke resolusi kamera AKTUAL yang sedang dipakai. Dipanggil sekali di
        __init__() dan bisa dipanggil ulang via set_camera_resolution().

        Kenapa ini penting: sebelumnya, mengganti resolusi kamera berarti mengedit
        MANUAL setiap konstanta piksel satu-per-satu di seluruh file ini (dan file
        lain: main.py, vision/tracker.py, Go entity, frontend) — proses yang TERBUKTI
        rawan bug (dua kali dalam pengembangan proyek ini ada nilai yang lupa
        di-rescale atau salah rescale). Dengan skala otomatis di sini, TIDAK ADA lagi
        konstanta yang perlu diedit manual saat resolusi berubah — cukup berikan
        camera_width/camera_height yang benar (lihat main.py), sisanya otomatis.

        Konvensi skala (SAMA seperti yang sudah dipakai di seluruh komentar rescale
        640→1920 di file ini sebelumnya):
          - Jarak piksel LINEAR (mis. jarak identitas bola, lebar pasangan maksimum):
            diskalakan dengan rasio LEBAR saja (camera_width / REFERENCE_FRAME_WIDTH).
          - AREA piksel² (mis. luas minimum pasangan untuk LOCK): diskalakan dengan
            rasio LEBAR × TINGGI, BUKAN cuma rasio lebar — luas adalah besaran 2D.

        Nilai selalu dihitung dari konstanta CLASS (MissionEngine.<NAMA>), BUKAN dari
        self.<NAMA> — mencegah "double-scaling" kalau method ini dipanggil lebih dari
        sekali (lihat set_camera_resolution()). Hasil disimpan sebagai ATRIBUT
        INSTANCE dengan nama PERSIS SAMA seperti konstanta class-nya, sehingga
        otomatis menimpa (shadow) nilai class di setiap tempat lain yang mengakses
        self.<NAMA> — TIDAK ADA satu pun tempat lain di file ini yang perlu diubah.

        Kalau camera_width/height == resolusi referensi (default __init__), scale
        factor = 1.0 dan hasilnya IDENTIK dengan nilai class asli — TIDAK ADA
        perubahan perilaku untuk setup yang sudah ada (1920x1080).
        """
        self.camera_width = int(camera_width)
        self.camera_height = int(camera_height)

        px_scale = self.camera_width / float(MissionEngine.REFERENCE_FRAME_WIDTH)
        area_scale = px_scale * (self.camera_height / float(MissionEngine.REFERENCE_FRAME_HEIGHT))

        # Disimpan supaya nilai piksel yang datang DARI STEP MISI ikut diskalakan —
        # lihat _px_dari_step()/_area_dari_step(). Tanpa ini, field di panel misi
        # (yang defaultnya ditulis dalam satuan referensi 1920x1080, disalin dari
        # konstanta di atas) dipakai MENTAH pada resolusi berapa pun. Dikonfirmasi di
        # lapangan: di 1280x720 nilai default 60000px² membuat kapal harus mendekat
        # 2,25x lebih dekat dari yang dimaksud — nyaris menyentuh box.
        self._px_scale = px_scale
        self._area_scale = area_scale

        # Jarak piksel LINEAR — skala LEBAR
        self.GATE_IDENTITY_MAX_DIST_PX = round(MissionEngine.GATE_IDENTITY_MAX_DIST_PX * px_scale)
        self.SEQ_SINGLE_BALL_CLEARANCE_PX = round(MissionEngine.SEQ_SINGLE_BALL_CLEARANCE_PX * px_scale)
        self.SEQ_MAX_PAIR_WIDTH_PX = round(MissionEngine.SEQ_MAX_PAIR_WIDTH_PX * px_scale)
        self.SEQ_IDENTITY_MAX_DIST_PX = round(MissionEngine.SEQ_IDENTITY_MAX_DIST_PX * px_scale)
        self.SEQ_CLEARED_EXCLUSION_RADIUS_PX = round(MissionEngine.SEQ_CLEARED_EXCLUSION_RADIUS_PX * px_scale)

        self.PHOTO_ALIGN_THRESHOLD_PX = round(MissionEngine.PHOTO_ALIGN_THRESHOLD_PX * px_scale)
        self.BOXCH_ALIGN_THRESHOLD_PX = round(MissionEngine.BOXCH_ALIGN_THRESHOLD_PX * px_scale)
        self.BOXCH_CHANNEL_OFFSET_PX = round(MissionEngine.BOXCH_CHANNEL_OFFSET_PX * px_scale)
        self.BAP_CENTER_TOLERANCE_PX = round(MissionEngine.BAP_CENTER_TOLERANCE_PX * px_scale)
        self.DOCK_ALIGN_TOLERANCE_PX = round(MissionEngine.DOCK_ALIGN_TOLERANCE_PX * px_scale)

        # AREA piksel² — skala LEBAR × TINGGI
        self.SEQ_MIN_PAIR_AREA_PX2 = round(MissionEngine.SEQ_MIN_PAIR_AREA_PX2 * area_scale)
        self.SEQ_IGNORE_AREA_PX2 = round(MissionEngine.SEQ_IGNORE_AREA_PX2 * area_scale)
        self.PHOTO_MIN_AREA_PX2_BLUE = round(MissionEngine.PHOTO_MIN_AREA_PX2_BLUE * area_scale)
        self.PHOTO_MIN_AREA_PX2_GREEN = round(MissionEngine.PHOTO_MIN_AREA_PX2_GREEN * area_scale)
        self.BOXCH_MIN_AREA_PX2_BLUE = round(MissionEngine.BOXCH_MIN_AREA_PX2_BLUE * area_scale)
        self.BOXCH_MIN_AREA_PX2_GREEN = round(MissionEngine.BOXCH_MIN_AREA_PX2_GREEN * area_scale)
        self.BAP_TARGET_AREA_PX2 = round(MissionEngine.BAP_TARGET_AREA_PX2 * area_scale)
        self.BAP_MIN_DETECT_AREA_PX2 = round(MissionEngine.BAP_MIN_DETECT_AREA_PX2 * area_scale)
        self.DOCK_RAM_AREA_PX2 = round(MissionEngine.DOCK_RAM_AREA_PX2 * area_scale)
        self.DOCK_MIN_DETECT_AREA_PX2 = round(MissionEngine.DOCK_MIN_DETECT_AREA_PX2 * area_scale)

        if self.camera_width != MissionEngine.REFERENCE_FRAME_WIDTH or self.camera_height != MissionEngine.REFERENCE_FRAME_HEIGHT:
            print(f"[MissionEngine] 📐 Threshold piksel diskalakan dari referensi "
                  f"{MissionEngine.REFERENCE_FRAME_WIDTH}x{MissionEngine.REFERENCE_FRAME_HEIGHT} "
                  f"ke {self.camera_width}x{self.camera_height} "
                  f"(px_scale={px_scale:.3f}, area_scale={area_scale:.3f})")

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _reset_gate_state_machine(self):
        """Reset semua variabel Gate State Machine ke kondisi awal (SEARCHING)."""
        self._gate_lock_state      = self.GATE_SEARCHING
        self._locked_red_pos       = None
        self._locked_green_pos     = None
        self._locked_entry_area    = None
        self._missing_color        = None
        self._transition_steer     = 0.0
        self._gate_state_entered_at = 0.0
        self._gate_pause_start     = 0.0

    @staticmethod
    def _bbox_area(ball: Tuple) -> float:
        """Area bounding box (piksel²) dari tuple (cx, cy, x1, y1, x2, y2)."""
        return float((ball[4] - ball[2]) * (ball[5] - ball[3]))

    def _pair_avg_area(self, red_ball: Tuple, green_ball: Tuple) -> float:
        """Rata-rata area bounding box (piksel²) dari sepasang bola merah+hijau."""
        return (self._bbox_area(red_ball) + self._bbox_area(green_ball)) / 2.0

    def _pick_single_ball_candidate(
        self, balls: Dict, min_area_px2: float
    ) -> Optional[Tuple[Tuple, str]]:
        """
        Dipanggil HANYA saat _sort_buoy_pairs() gagal membentuk pasangan valid sama
        sekali (pairs kosong) — entah karena cuma 1 warna yang terdeteksi, ATAU
        kedua warna ADA tapi gagal lolos safeguard rasio-area/lebar-maksimum di
        sort_ball_pairs() (mis. bola merah dari gate ini + bola hijau dari gate
        lain/refleksi yang kebetulan sama-sama masuk frame tapi bukan pasangan yang
        sama). Di KEDUA kasus itu, tidak ada pasangan yang bisa dipercaya — pilih
        SATU bola individu terbesar/terdekat (warna apa saja, dari kedua list,
        BUKAN mensyaratkan warna lain kosong) sebagai target HINDAR, asalkan
        area-nya >= min_area_px2.

        PENTING: sebelumnya fungsi ini mensyaratkan warna lain harus KOSONG total
        (elif red and not green / green and not red) — kalau kedua warna sama-sama
        ADA tapi tidak berhasil dipasangkan, kapal tetap jatuh ke fallback gate_x
        lama yang mengejar (chase) posisi bola, bukan menghindarinya. Itu bug yang
        sama persis dengan yang seharusnya sudah diperbaiki oleh manuver hindar ini.

        Return (ball, color) — color "red" atau "green" — atau None kalau tidak ada
        bola sama sekali atau semuanya di bawah min_area_px2 (caller jatuh ke
        fallback gate_x / blind). Yang dikembalikan adalah WARNA bola, bukan sisi
        kiri/kanan: sisinya diturunkan dari warna lewat vision/gate_convention.py.
        """
        red = balls.get("red", [])
        green = balls.get("green", [])
        candidates = []
        if red:
            candidates.append((red[0], "red"))      # sudah sorted foreground-first
        if green:
            candidates.append((green[0], "green"))
        if not candidates:
            return None
        best_ball, best_color = max(candidates, key=lambda c: self._bbox_area(c[0]))
        if self._bbox_area(best_ball) >= min_area_px2:
            return best_ball, best_color
        return None

    def _blind_lean_steer(self, step: Dict) -> float:
        """
        Kemudi saat kapal bergerak "buta" — tidak ada buoy sama sekali di frame.

        step['blind_lean_percent'] (-100..+100): negatif = miring KIRI, positif = miring
        KANAN, 0 = maju lurus (perilaku lama). Dipakai bersama step['throttle'] sebagai
        kecepatannya dan step['blind_search_timeout_sec'] sebagai lamanya.

        Kenapa persen dan bukan derajat: nilainya diteruskan langsung sebagai steer
        ternormalisasi (-1..+1) ke RC override, satuan yang sama dengan seluruh kemudi
        di file ini. Derajat akan menyiratkan yaw rate yang dijamin, padahal di mode
        MANUAL tidak ada yang menutup loop-nya — sudut sesungguhnya bergantung throttle,
        arus, dan angin.

        Nilai di luar rentang di-clamp, BUKAN ditolak: field ini diketik operator di
        panel misi, dan salah ketik tidak boleh berujung kemudi liar.
        """
        percent = self._safe_float(step.get("blind_lean_percent"), 0.0)
        return max(-1.0, min(1.0, percent / 100.0))

    @staticmethod
    def _lean_steer_for_missing(missing_color: str, magnitude: float) -> float:
        """
        Arah & besar steer condong saat TRANSITIONING, dari WARNA bola yang hilang
        duluan. Kapal menahan haluan KE ARAH SISI bola yang hilang itu — bola tersebut
        keluar lewat tepi frame di sisinya, artinya haluan sudah menjauh dari sisi itu
        dan perlu ditarik balik agar kapal tetap melintas di tengah celah.

        Sisi setiap warna HANYA berasal dari vision/gate_convention.py — jangan pernah
        menuliskannya sebagai literal "left"/"right" di file ini.
        """
        return steer_sign_toward(side_of(missing_color)) * magnitude

    @staticmethod
    def _lean_arrow(missing_color: Optional[str]) -> str:
        """Panah OSD (←/→) untuk arah condong TRANSITIONING; "?" kalau warna belum di-set."""
        if missing_color is None:
            return "?"
        return "←" if side_of(missing_color) == LEFT else "→"

    def _compute_single_ball_avoid_steer(self, ball: Tuple, color: str, step: Dict) -> float:
        """
        Koreksi TAMBAHAN (aditif) untuk menjaga jarak dari satu bola yang sedang
        dilintasi, dipakai saat kapal sudah punya target lain — yaitu saat handoff
        TRANSITIONING membidik gerbang BERIKUTNYA sementara bola sisa gerbang ini
        masih fisik berada di samping kapal.

        Dipakai di DUA tempat:
          1. SEARCHING, saat tidak ada pasangan valid sama sekali — bola tunggal itu
             satu-satunya acuan yang ada.
          2. Handoff TRANSITIONING, sebagai tambahan di atas steer ke gerbang
             BERIKUTNYA, karena bola sisa gerbang ini masih fisik di samping kapal.

        Bentuknya sengaja REPULSIF (diam selama bola masih di sisinya yang wajar, baru
        mendorong saat bola merangsek melewati garis amannya), BUKAN atraktif ("bidik
        titik tengah semu = bola ± setengah lebar gerbang"). Bentuk atraktif sempat
        dicoba dan TERBUKTI DI SIMULATOR (tools/buoy_sim.py) membuat kapal goyah lalu
        menabrak: saat kedua bola satu gerbang terlihat tapi gagal dipasangkan (lebar
        pasangan melebihi max_pair_width_px — sering terjadi TEPAT saat kapal berada di
        mulut gerbang), _pick_single_ball_candidate() bergantian memilih bola merah lalu
        bola hijau karena area keduanya nyaris sama. Dua tebakan titik tengah dari dua
        bola yang berjauhan itu saling bertolak belakang, sehingga kemudi membanting
        bolak-balik ±max_steer tiap frame (28 kali ganti arah per run, 5 tabrakan).
        Bentuk repulsif ini kebal terhadap pergantian kandidat tersebut: selama kedua
        bola masih di sisinya masing-masing, KEDUANYA menghasilkan 0.0 — kapal jalan
        lurus melewati mulut gerbang, bukan menebak lebar gerbang yang sebenarnya tidak
        ia ketahui.

        Titik tengah semu tetap dihitung untuk fallback visual `gate_x` di
        vision/tracker.py (nilai yang ditampilkan di OSD & dicatat blackbox) lewat
        gate_convention.virtual_gate_center_x() — di sana yang dibutuhkan memang sebuah
        KOORDINAT titik tengah, bukan koreksi kemudi.

        Garis aman bola = clearance_px dari haluan, DI SISI bola itu seharusnya berada:

            safe_x       = center_x - channel_sign(warna) * clearance_px
            encroachment = channel_sign(warna) * (ball_x - safe_x)

        encroachment > 0 berarti bola sudah lebih dekat ke haluan daripada garis
        amannya (atau bahkan sudah menyeberang ke sisi yang salah) → dorong kapal ke
        arah lintasan, yaitu channel_sign(warna), sebesar proporsi pelanggarannya.

        PENTING — kenapa BUKAN abs(ball_x - center_x) seperti versi lama: ukuran
        mutlak itu tidak bisa membedakan bola yang aman di sisinya dari bola yang
        sudah menyeberang ke sisi yang salah (keduanya menghasilkan angka yang sama),
        sehingga koreksinya memuncak tepat di garis tengah frame lalu MENGECIL lagi
        justru ketika bola makin jauh menyeberang — dan arahnya tidak pernah ikut
        membalik. Bentuk bertanda di sini kontinu, monoton, dan tetap penuh selama
        bola berada di sisi yang salah.
        """
        clearance_px = self._safe_float(step.get("single_ball_clearance_px"),
                                        self.SEQ_SINGLE_BALL_CLEARANCE_PX)
        max_steer = abs(self._safe_float(step.get("single_ball_max_steer"),
                                         self.SEQ_SINGLE_BALL_MAX_STEER))
        if clearance_px <= 0:
            return 0.0

        center_x = self.tracking_controller.center_x
        sign = channel_sign(color)
        safe_x = center_x - sign * clearance_px
        encroachment = sign * (float(ball[0]) - safe_x)
        if encroachment <= 0.0:
            # Bola masih aman di sisinya sendiri → jangan ganggu steer target utama.
            return 0.0

        urgency = min(1.0, encroachment / clearance_px)
        return sign * urgency * max_steer

    def _find_next_pair_excluding(
        self, detected_balls: Dict, exclude_side: Optional[str],
        exclude_ball: Optional[Tuple], min_area_px2: float
    ) -> Optional[Tuple]:
        """
        Cari pasangan gerbang BERIKUTNYA yang valid, dengan MEMBUANG dulu bola sisa
        gerbang yang sedang dilewati (`exclude_ball` pada sisi `exclude_side`).

        Dipakai saat TRANSITIONING untuk "handoff": begitu satu bola gerbang saat ini
        hilang, kapal pindah membidik gerbang berikutnya alih-alih condong buta.

        Pembuangan bola sisa itu WAJIB, bukan opsional: kalau tidak dibuang,
        _sort_buoy_pairs() bisa memasangkannya dengan bola gerbang BERIKUTNYA dan
        menghasilkan "gerbang hantu" yang titik tengahnya mengarah ke tempat yang
        salah — persis false-pairing yang sudah lama dijaga di file ini.

        PENTING — buang berdasarkan IDENTITAS PERSIS (posisi cx,cy bola itu sendiri),
        BUKAN radius. Versi pertama fungsi ini membuang semua bola dalam radius
        SEQ_IDENTITY_MAX_DIST_PX (450px @1920) dari bola sisa, dan itu terbukti
        (lewat test) IKUT MEMBUANG bola gerbang berikutnya — di arena nyata jarak
        antar-gerbang bisa lebih kecil dari radius itu (mis. ~331px), sehingga
        handoff tidak pernah aktif sama sekali. `exclude_ball` selalu berasal dari
        `detected_balls` frame ini juga, jadi pencocokan posisi persis aman.

        Return (red_ball, green_ball) atau None kalau tidak ada pasangan valid.
        """
        filtered = {"red": list(detected_balls.get("red", [])),
                    "green": list(detected_balls.get("green", []))}
        if exclude_ball is not None and exclude_side in filtered:
            ex, ey = exclude_ball[0], exclude_ball[1]
            filtered[exclude_side] = [
                b for b in filtered[exclude_side]
                if not (b[0] == ex and b[1] == ey)
            ]

        for red_ball, green_ball in self._sort_buoy_pairs(filtered):
            if self._pair_avg_area(red_ball, green_ball) >= min_area_px2:
                return red_ball, green_ball
        return None

    def _compute_gate_clearance_steer(self, red_x: float, green_x: float, step: Dict) -> float:
        """
        Koreksi tambahan saat LOCKED: jaga agar haluan kapal berada di tengah CELAH
        secara PROPORSIONAL, diukur relatif terhadap lebar gerbang saat itu.

        ── Kenapa steer midpoint saja TIDAK cukup (penyebab kapal menabrak bola) ──
        Steer midpoint memakai error dalam PIKSEL MUTLAK: (midpoint − tengah_frame).
        Error piksel yang sama bisa berarti "masih aman" ATAU "hampir nabrak",
        tergantung selebar apa gerbangnya tampak saat itu — dan midpoint TIDAK
        membedakan keduanya. Contoh nyata (tengah frame = 960):

          bola kiri=800, bola kanan=1000 → error midpoint = −60 px
              celah kiri 160px, celah kanan HANYA 40px → bola kanan nyaris di haluan!
          bola kiri=700, bola kanan=1100 → error midpoint = −60 px  (SAMA PERSIS)
              celah kiri 260px, celah kanan 140px → masih relatif aman

        Kedua kasus menghasilkan koreksi yang identik dari steer midpoint, padahal
        tingkat bahayanya jauh berbeda. Itulah celah yang membuat kapal menyenggol.

        CATATAN PENTING (sudah diverifikasi secara aljabar, jangan diganti balik):
        pendekatan "jaga jarak MUTLAK per-bola dalam piksel" TIDAK menyelesaikan ini —
        di area linearnya, hasilnya terbukti hanya KELIPATAN KONSTAN dari error
        midpoint (guard/error = konstan), alias cuma menaikkan gain PID tanpa
        menambah informasi baru sama sekali, dan tetap memberi koreksi identik untuk
        kedua contoh di atas.

        ── Solusinya: normalisasi terhadap lebar gerbang ──
          left_gap  = tengah_frame − bola_kiri_x   (celah di sisi kiri haluan)
          right_gap = bola_kanan_x − tengah_frame  (celah di sisi kanan haluan)
          imbalance = (right_gap − left_gap) / (right_gap + left_gap)   → −1..+1

        imbalance = 0  → haluan tepat di tengah celah (aman, tidak ada koreksi)
        imbalance > 0  → celah kanan lebih lega, bola KIRI lebih dekat → dorong KANAN (+)
        imbalance < 0  → celah kiri lebih lega, bola KANAN lebih dekat → dorong KIRI (−)
        imbalance = ±1 → salah satu bola TEPAT di garis haluan (paling bahaya)

        BOLA MANA YANG DI KIRI/KANAN diambil dari vision/gate_convention.py, TIDAK
        diasumsikan di sini. Versi lama menganggap merah selalu di kiri; di arena yang
        memakai konvensi sebaliknya (merah KANAN, hijau KIRI) kedua celah jadi negatif
        sehingga total_gap <= 0 dan guard ini MATI TOTAL tanpa suara — kapal kehilangan
        seluruh perlindungan anti-senggol ini tanpa satu pun log yang menandakannya.

        Karena dibagi lebar gerbang, error piksel yang sama otomatis menghasilkan
        koreksi LEBIH BESAR saat gerbang tampak sempit (jauh/sempit = berbahaya) dan
        LEBIH KECIL saat gerbang tampak lebar (dekat/lega = aman) — persis yang
        dibutuhkan, dan inilah informasi yang benar-benar BARU dibanding steer
        midpoint. Untuk dua contoh di atas: kasus pertama imbalance = −0.60
        (koreksi kuat), kasus kedua −0.30 (koreksi setengahnya).

        `gate_balance_deadband` memberi toleransi ketidakseimbangan wajar supaya guard
        ini tidak terus-menerus melawan tracking midpoint normal saat kapal sebetulnya
        sudah cukup di tengah.
        """
        deadband = self._safe_float(step.get("gate_balance_deadband"), self.SEQ_GATE_BALANCE_DEADBAND)
        max_steer = self._safe_float(step.get("gate_max_avoid_steer"), self.SEQ_GATE_MAX_AVOID_STEER)

        center_x = self.tracking_controller.center_x
        # Petakan warna → tepi kiri/kanan lewat konvensi tunggal (lihat docstring).
        if side_of("red") == LEFT:
            left_x, right_x = red_x, green_x
        else:
            left_x, right_x = green_x, red_x

        left_gap = center_x - left_x     # celah sisi kiri haluan
        right_gap = right_x - center_x   # celah sisi kanan haluan
        total_gap = left_gap + right_gap

        # Kapal sudah DI LUAR gerbang (kedua bola di sisi yang sama) atau lebar 0 —
        # tidak ada "celah" yang bermakna untuk dinormalisasi. Serahkan ke steer
        # midpoint biasa, jangan menghasilkan koreksi ngawur dari pembagian aneh.
        if total_gap <= 0:
            return 0.0

        imbalance = (right_gap - left_gap) / total_gap
        imbalance = max(-1.0, min(1.0, imbalance))

        deadband = max(0.0, min(0.99, deadband))
        magnitude = abs(imbalance)
        if magnitude <= deadband:
            return 0.0

        urgency = (magnitude - deadband) / (1.0 - deadband)
        direction = 1.0 if imbalance > 0 else -1.0
        return max(-1.0, min(1.0, direction * urgency * max_steer))

    @staticmethod
    def _safe_bool(value: Any, default: bool) -> bool:
        """
        Konversi field step mission ke bool dengan aman.

        WAJIB hati-hati di sini: frontend mengirim angka 1/0 (input bertipe number),
        bukan true/false. Cek naif seperti `value is not False` SALAH untuk angka —
        di Python `0 is False` bernilai False, sehingga 0 justru lolos sebagai "aktif"
        dan toggle-nya tidak pernah bisa dimatikan. Tangani angka, string, dan bool
        secara eksplisit; nilai kosong/None/tidak valid jatuh ke `default`.
        """
        if value is None or value == "":
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("0", "false", "no", "off"):
                return False
            if v in ("1", "true", "yes", "on"):
                return True
        return default

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        """
        Konversi nilai field step mission ke float dengan aman — kembalikan `default`
        kalau value None, string kosong, atau tidak valid, BUKAN melempar ValueError.

        KENAPA INI PENTING (bukan sekadar jaga-jaga): dikonfirmasi crash di lapangan —
        field "steer" pada step TIMED_STEER berisi string kosong ('') karena input
        number di frontend sempat dikosongkan operator sebelum mission di-upload,
        dan `float('')` melempar ValueError. Exception itu terjadi DI DALAM
        frame_callback yang dipanggil dari _upload_loop() (camera/streamer.py) TANPA
        try/except membungkusnya — akibatnya seluruh thread streaming+kontrol MATI
        total (bukan cuma 1 step yang gagal), kapal berhenti menerima RC command baru
        sama sekali sampai di-restart manual. Safety net di camera/streamer.py &
        main.py sudah ditambahkan sebagai lapis pertahanan luar, TAPI parsing di sini
        tetap harus aman sendiri sebagai lapis pertama — jangan andalkan lapisan luar
        saja untuk kasus yang seharusnya bisa dicegah di sumbernya.

        Pemanggilan: `self._safe_float(step.get("key"), default)` — SENGAJA tanpa
        default kedua di `step.get()` (beda dari pola lama `step.get("key", default)`)
        karena `step.get()` hanya memberi default saat KEY TIDAK ADA, sedangkan kasus
        di atas key ADA tapi isinya '' — _safe_float menangani KEDUA kasus itu sekaligus.
        """
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        """Versi int() dari _safe_float() — lihat catatan di sana."""
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _resolve_step_throttle(self, step: Dict) -> float:
        """
        Ambil throttle (0.0-1.0) dari field `throttle` step mission jika diisi,
        jika tidak fallback ke speed_scheduler.max_base_throttle (global, live-tunable
        via WS PID config). Dipakai TRACKING_BUOY & SEQUENTIAL_BUOY agar tiap step bisa
        override kecepatan majunya sendiri, konsisten dengan CUSTOM_FORWARD (speed_mps)
        dan TIMED_STEER (throttle) yang sudah lebih dulu configurable per-step.
        """
        step_throttle = step.get("throttle")
        if step_throttle is not None:
            resolved = self._safe_float(step_throttle, -1.0)
            if resolved >= 0.0:
                return max(0.0, min(1.0, resolved))
        return self.speed_scheduler.max_base_throttle

    def _find_nearest_ball(
        self,
        balls: List[Tuple],
        locked_pos: Optional[Tuple[int, int]],
        locked_area: Optional[float] = None,
        min_area_ratio: Optional[float] = None,
        max_dist_px: Optional[float] = None,
    ) -> Optional[Tuple]:
        """
        Temukan bola dari list yang paling dekat dengan locked_pos
        dan masih dalam threshold jarak (default GATE_IDENTITY_MAX_DIST_PX).

        Jika `locked_area` & `min_area_ratio` diberikan, kandidat yang area bbox-nya
        jauh lebih kecil dari `locked_area` (rasio < min_area_ratio) DITOLAK meskipun
        jaraknya secara piksel masuk threshold — ini mencegah bola dari gate lain
        (lebih jauh dari kamera → bbox lebih kecil) diambil-alih sebagai identitas
        bola yang sedang dikunci.

        `max_dist_px` opsional meng-override threshold jarak default
        (GATE_IDENTITY_MAX_DIST_PX) — dipakai SEQUENTIAL_BUOY dengan radius LEBIH
        KETAT (SEQ_IDENTITY_MAX_DIST_PX) karena arena-nya bisa punya banyak gate
        berdekatan. Semua parameter opsional agar caller lama (TRACKING_BUOY)
        tetap berperilaku sama persis tanpa perubahan.

        Returns: tuple (cx, cy, x1, y1, x2, y2) atau None jika tidak ada yang memenuhi threshold.
        """
        if not balls or locked_pos is None:
            return None

        best = None
        best_dist = float("inf")
        lx, ly = locked_pos
        dist_threshold = max_dist_px if max_dist_px is not None else self.GATE_IDENTITY_MAX_DIST_PX

        for ball in balls:
            if locked_area is not None and min_area_ratio is not None and locked_area > 0:
                ball_area = self._bbox_area(ball)
                if (ball_area / locked_area) < min_area_ratio:
                    # Bola jauh lebih kecil dari yang terakhir dikunci → kemungkinan besar
                    # bukan bola yang sama (mis. bola gate berikutnya), abaikan sepenuhnya.
                    continue
            cx, cy = ball[0], ball[1]
            dist = math.hypot(cx - lx, cy - ly)
            if dist < best_dist:
                best_dist = dist
                best = ball

        if best_dist <= dist_threshold:
            return best
        return None  # Bola terlalu jauh → bola gerbang lain, abaikan

    def _advance_step(self):
        # Buka kunci PHOTO_BOX kalau step yang BARU SAJA selesai adalah step buoy.
        # Ditaruh di sini, bukan di tiap handler, karena SEMUA jalur penyelesaian
        # step lewat sini — termasuk yang selesai karena timeout SEARCHING atau
        # karena buoy habis dari frame, yang mudah terlewat kalau flag-nya disetel
        # satu per satu di dalam handler.
        if self._current_step_idx < len(self._steps):
            baru_selesai = self._steps[self._current_step_idx].get("type", "")
            if baru_selesai in self.BUOY_STEP_TYPES and not self._tracking_buoy_completed:
                self._tracking_buoy_completed = True
                print(f"[MissionEngine] 🔓 Step buoy '{baru_selesai}' selesai — "
                      f"PHOTO_BOX sekarang boleh dijalankan.")

        self._current_step_idx += 1
        self._step_start_time = None
        self._paused_step_elapsed = 0.0
        self._last_goto_time = 0.0
        self._reset_gate_state_machine()
        self._buoy_pass_count = 0  # Reset counter untuk step tracking berikutnya
        # Reset PRECISION_TURN state
        self._turn_initial_heading = None
        self._turn_target_heading  = None
        # Reset GYRO_FORWARD state
        self._cruise_initial_heading = None
        self._cruise_ball_seen_since = None
        self._steer_gate_seen_since = None
        self._steer_box_seen_since = None

        if self._current_step_idx < len(self._steps):
            next_step = self._steps[self._current_step_idx]
            print(f"[MissionEngine] ➡️ Step #{self._current_step_idx + 1}: {next_step.get('name', '?')} ({next_step.get('type', '?')})")
        self._broadcast_status()

    def _finish_mission(self):
        self._status = self.STATUS_FINISHED
        self._stop_elapsed_timer()
        self.asv.stop_movement()  # Hentikan gerak, JANGAN ubah mode
        print("[MissionEngine] 🎉 MISSION FINISHED SUCCESSFULLY!")
        self._broadcast_status()

    def _haversine(self, lat1, lon1, lat2, lon2) -> float:
        """Hitung jarak di permukaan bumi dalam meter."""
        R = 6371000.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def _broadcast_status(self):
        if self._status_callback:
            try:
                self._status_callback(self.get_status_dict())
            except Exception as e:
                print(f"[MissionEngine] Callback error: {e}")

    def _start_elapsed_timer(self):
        self._elapsed_running = True
        self._elapsed_thread = threading.Thread(target=self._elapsed_loop, daemon=True)
        self._elapsed_thread.start()

    def _stop_elapsed_timer(self):
        self._elapsed_running = False

    def _elapsed_loop(self):
        while self._elapsed_running:
            time.sleep(1)
            if self._status == self.STATUS_RUNNING:
                self._elapsed_sec += 1
                # Broadcast setiap detik agar frontend sync waktu elapsed
                self._broadcast_status()
