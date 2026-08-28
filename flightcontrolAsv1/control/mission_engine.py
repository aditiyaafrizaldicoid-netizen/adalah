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

import time
import math
import threading
from typing import Optional, List, Dict, Any, Tuple


from control.speed_scheduler import SpeedScheduler
from vision.ball_pairing import sort_ball_pairs
from vision.gate_convention import (
    LEFT,
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
    STEP_TYPE_SEQUENTIAL_BUOY = "SEQUENTIAL_BUOY"  # Lewati N pasang buoy (hijau+merah) secara berurutan
    STEP_TYPE_GYRO_FORWARD   = "GYRO_FORWARD"    # Maju lurus dgn koreksi yaw kompas/gyro, berhenti di waktu ATAU saat buoy terdeteksi
    STEP_TYPE_BUOY_CHASE     = "BUOY_CHASE"      # Versi sederhana SEQUENTIAL_BUOY: cuma throttle + filter jarak (px²), selesai saat buoy habis dari frame

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
            }

    # ------------------------------------------------------------------ #
    #  Frame Update Loop (dipanggil dari video_streamer callback ~30FPS)  #
    # ------------------------------------------------------------------ #

    def update_frame(self, frame, gate_x: Optional[float], detected_balls: Optional[Dict] = None):
        """
        Dipanggil oleh process_and_control() setiap frame.

        :param frame:          Frame kamera saat ini.
        :param gate_x:         Koordinat X midpoint gate dari tracker (fallback/visual).
        :param detected_balls: Dict {"red": [...], "green": [...]} dari tracker.process_frame().
                               Masing-masing berisi list (cx, cy, x1, y1, x2, y2).

        Return: (steer_norm, thr_norm, step_type_label)
        """
        with self._lock:
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
                elif step_type == self.STEP_TYPE_TIMED_STEER:
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch mode → MANUAL untuk TIMED_STEER...")
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

            # ---- SEQUENTIAL_BUOY ----
            elif step_type == self.STEP_TYPE_SEQUENTIAL_BUOY:
                return self._handle_sequential_buoy(step, gate_x, detected_balls or {"red": [], "green": []})

            # ---- GYRO_FORWARD ----
            elif step_type == self.STEP_TYPE_GYRO_FORWARD:
                return self._handle_gyro_forward(step, detected_balls or {"red": [], "green": []})

            # ---- BUOY_CHASE ----
            elif step_type == self.STEP_TYPE_BUOY_CHASE:
                return self._handle_buoy_chase(step, gate_x, detected_balls or {"red": [], "green": []})

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
        """Handle TAKE_IMAGE step."""
        duration = self._safe_float(step.get("duration_sec"), 3.0)
        elapsed = time.time() - self._step_start_time

        if elapsed >= duration:
            print(f"[MissionEngine] ✅ TAKE_IMAGE selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x, detected_balls)

        return 0.0, 0.0, "TAKE_IMAGE"

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

                    if blind_duration > self.SEQ_BLIND_SEARCH_TIMEOUT_SEC:
                        label = (f"SEQ_GATE:SEARCHING (blind {blind_duration:.1f}s, HOLD) "
                                 f"| SEQUENTIAL_BUOY (pair {pair_label})")
                        return 0.0, 0.0, label
                    label = f"SEQ_GATE:SEARCHING (no target) | SEQUENTIAL_BUOY (pair {pair_label})"
                    return 0.0, throttle, label

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

        # Jarak piksel LINEAR — skala LEBAR
        self.GATE_IDENTITY_MAX_DIST_PX = round(MissionEngine.GATE_IDENTITY_MAX_DIST_PX * px_scale)
        self.SEQ_SINGLE_BALL_CLEARANCE_PX = round(MissionEngine.SEQ_SINGLE_BALL_CLEARANCE_PX * px_scale)
        self.SEQ_MAX_PAIR_WIDTH_PX = round(MissionEngine.SEQ_MAX_PAIR_WIDTH_PX * px_scale)
        self.SEQ_IDENTITY_MAX_DIST_PX = round(MissionEngine.SEQ_IDENTITY_MAX_DIST_PX * px_scale)
        self.SEQ_CLEARED_EXCLUSION_RADIUS_PX = round(MissionEngine.SEQ_CLEARED_EXCLUSION_RADIUS_PX * px_scale)

        # AREA piksel² — skala LEBAR × TINGGI
        self.SEQ_MIN_PAIR_AREA_PX2 = round(MissionEngine.SEQ_MIN_PAIR_AREA_PX2 * area_scale)
        self.SEQ_IGNORE_AREA_PX2 = round(MissionEngine.SEQ_IGNORE_AREA_PX2 * area_scale)

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
