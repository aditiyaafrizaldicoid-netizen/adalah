"""
MissionEngine - Autonomous Mission Sequence Executor untuk ASV.

Engine ini mengeksekusi mission steps secara berurutan:
- TRACKING_BUOY  : AI Vision PID untuk melewati gerbang bola hijau+merah
- SEQUENTIAL_BUOY: Lewati N pasang buoy (hijau+merah) berurutan tanpa perlu di-configure jumlahnya
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
  - Bola kiri (merah) hilang duluan → kapal DIPAKSA condong ke KIRI (steer negatif konstan)
  - Bola kanan (hijau) hilang duluan → kapal DIPAKSA condong ke KANAN (steer positif konstan)
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
    # Nilai default 4000px² @ 1920x1080 dipilih SENGAJA sama dengan nilai ASLI
    # SEQ_MIN_PAIR_AREA_PX2 sebelum diskalakan ke resolusi 1920x1080 (dulu
    # 4000px² @ 640x480) — di resolusi baru ini otomatis jadi jauh lebih kecil
    # relatif terhadap frame, cocok sebagai noise-floor kasar. BELUM diverifikasi
    # di lapangan pada resolusi ini — naikkan kalau kapal masih tertarik ke buoy
    # yang sangat jauh, turunkan kalau buoy dekat yang sah malah ikut terbuang.
    SEQ_IGNORE_AREA_PX2 = 4000

    # ── Single-Ball Avoidance (Sequential Buoy) ─────────────────────────────
    # Saat SEARCHING dan HANYA SATU warna bola yang terdeteksi (pasangan gagal
    # terbentuk sama sekali — bukan kasus "pasangan terlalu jauh untuk dikunci" di
    # atas), kapal TIDAK boleh mengejar/menyejajarkan diri ke bola itu (itu akan
    # menabraknya begitu bola makin dekat ke tengah frame). Sebaliknya, kapal harus
    # MENJAGA JARAK bola tersebut terhadap titik tengah kamera — dikoreksi MENJAUH
    # dari sisi bola itu, sebanding dengan seberapa dekat bola ke tengah frame saat
    # ini (bola dekat tengah = haluan kapal lurus ke arahnya = bahaya, butuh koreksi
    # kuat; bola sudah jauh dari tengah = clearance aman, koreksi kecil/tidak ada).
    # Arah menjauh mengikuti konvensi sisi gerbang yang sudah ada di file ini: bola
    # HIJAU (kanan) terlihat sendirian → kapal condong ke KIRI; bola MERAH (kiri)
    # terlihat sendirian → kapal condong ke KANAN.
    #
    # Sebelum ada logic ini, kapal memakai fallback gate_x mentah dari tracker.py
    # (bola ± offset piksel TETAP 20% lebar frame) yang diumpankan ke PID steering
    # yang sama dengan target pasangan — efeknya kapal tetap "mengejar" posisi bola
    # itu setiap kali ia bergerak, bukan menjaga jarak darinya.

    # Jarak lateral (piksel) dari tengah frame yang dianggap "aman" dari bola
    # tunggal. Di bawah jarak ini, koreksi menjauh mulai diterapkan (maksimum saat
    # bola tepat di tengah frame). 384px @ 1920px (~20% lebar frame) — sengaja sama
    # dengan magnitude offset gate_x lama di tracker.py agar perilakunya familiar,
    # BELUM diverifikasi di lapangan sebagai jarak clearance yang optimal.
    SEQ_SINGLE_BALL_CLEARANCE_PX = 384

    # Steer maksimum (0..1) untuk koreksi menjaga-jarak dari bola tunggal, dicapai
    # saat bola tepat di tengah frame (urgency=1.0). Disamakan dengan
    # TRANSITION_LEAN_MAGNITUDE agar skalanya konsisten dengan manuver
    # condong/menghindar lain di file ini.
    SEQ_SINGLE_BALL_MAX_STEER = TRANSITION_LEAN_MAGNITUDE

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
    # margin aman di bawah itu. Sekarang 600px @ 1920px (kamera Logitech MX Brio,
    # diskalakan 3x linear mengikuti lebar frame). KEMUNGKINAN BESAR PERLU
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

    def __init__(self, asv, tracker, tracking_controller, speed_scheduler: Optional[SpeedScheduler] = None):
        self.asv = asv
        self.tracker = tracker
        self.tracking_controller = tracking_controller
        self.speed_scheduler = speed_scheduler or SpeedScheduler(max_base_throttle=0.4)

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
        # Sisi bola mana yang hilang duluan saat TRANSITIONING ("left"=merah, "right"=hijau)
        self._missing_side: Optional[str] = None
        # Steer fallback yang dipertahankan selama TRANSITIONING jika bola tersisa tidak terdeteksi
        self._transition_steer: float = 0.0
        # Timestamp saat masuk ke state LOCKED / TRANSITIONING (untuk timeout guard)
        self._gate_state_entered_at: float = 0.0
        # Timestamp saat mission di-pause dalam state LOCKED/TRANSITIONING.
        # Digunakan untuk mengkompensasi durasi pause agar timeout tidak salah tembak saat resume.
        self._gate_pause_start: float = 0.0

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
        self._seq_missing_side: Optional[str] = None
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
                elif step_type == self.STEP_TYPE_SEQUENTIAL_BUOY:
                    if hasattr(self.tracking_controller, 'reset'):
                        self.tracking_controller.reset()
                    self._reset_sequential_state()
                    if self.asv and self.asv.is_connected() and self.asv.get_telemetry().mode != "MANUAL":
                        print("[MissionEngine] 🔄 Switch mode → MANUAL untuk SEQUENTIAL_BUOY...")
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
                warmup_sec = float(step.get("duration_sec", 2.0))
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
        """
        target_pass_count = int(step.get("pass_count", 0))
        duration = float(step.get("duration_sec", 0.0))

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
                self._gate_lock_state  = self.GATE_LOCKED
                self._gate_state_entered_at = time.time()
                print(f"[GATE] SEARCHING → LOCKED "
                      f"(red=({self._locked_red_pos}), green=({self._locked_green_pos}))")

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
            # Ini handle kasus kapal stuck menghadap gate tapi tidak bergerak maju.
            now = time.time()
            locked_duration = now - self._gate_state_entered_at
            if locked_duration > self.GATE_LOCKED_TIMEOUT_SEC and red_visible_locked and green_visible_locked:
                print(f"[GATE] LOCKED TIMEOUT ({locked_duration:.1f}s) → SEARCHING (reset untuk coba lagi)")
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
                # ★ Bola MERAH (kiri) hilang duluan → condong ke KIRI
                self._missing_side     = "left"
                self._gate_lock_state  = self.GATE_TRANSITIONING
                self._gate_state_entered_at = time.time()
                # Update posisi terakhir bola hijau yang terlihat
                self._locked_green_pos = (nearest_green[0], nearest_green[1])
                # Steer PAKSA konstan ke KIRI — pertahankan sampai bola hijau juga hilang.
                self._transition_steer = -self.TRANSITION_LEAN_MAGNITUDE
                print(f"[GATE] LOCKED → TRANSITIONING (missing=LEFT/red, lean={self._transition_steer:+.2f})")
                label = f"GATE:TRANSITIONING(←) | TRACKING_BUOY ({pass_label} pass)"
                return self._transition_steer, throttle, label

            elif red_visible_locked and not green_visible_locked:
                # ★ Bola HIJAU (kanan) hilang duluan → condong ke KANAN
                self._missing_side     = "right"
                self._gate_lock_state  = self.GATE_TRANSITIONING
                self._gate_state_entered_at = time.time()
                # Update posisi terakhir bola merah yang terlihat
                self._locked_red_pos   = (nearest_red[0], nearest_red[1])
                # Steer PAKSA konstan ke KANAN — pertahankan sampai bola merah juga hilang.
                self._transition_steer = self.TRANSITION_LEAN_MAGNITUDE
                print(f"[GATE] LOCKED → TRANSITIONING (missing=RIGHT/green, lean={self._transition_steer:+.2f})")
                label = f"GATE:TRANSITIONING(→) | TRACKING_BUOY ({pass_label} pass)"
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
            
            if self._missing_side == "left":
                # Bola merah sudah hilang, tinggal tunggu bola hijau juga hilang.
                nearest_green = self._find_nearest_ball(detected_balls.get("green", []), self._locked_green_pos)
                if nearest_green:
                    remaining_visible = True
                    self._locked_green_pos = (nearest_green[0], nearest_green[1])
                    # Steer tetap PAKSA konstan ke KIRI selama bola hijau masih terlihat —
                    # TIDAK mengikuti posisi bola hijau di layar (lihat TRANSITION_LEAN_MAGNITUDE).
                    self._transition_steer = -self.TRANSITION_LEAN_MAGNITUDE
            elif self._missing_side == "right":
                # Bola hijau sudah hilang, tinggal tunggu bola merah juga hilang.
                nearest_red = self._find_nearest_ball(detected_balls.get("red", []), self._locked_red_pos)
                if nearest_red:
                    remaining_visible = True
                    self._locked_red_pos = (nearest_red[0], nearest_red[1])
                    # Steer tetap PAKSA konstan ke KANAN selama bola merah masih terlihat.
                    self._transition_steer = self.TRANSITION_LEAN_MAGNITUDE

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
                lean_dir = "←" if self._missing_side == "left" else "→"
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
        target_pass_count = int(step.get("pass_count", 0))
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
        target_lat = float(step.get("lat", 0.0))
        target_lon = float(step.get("lon", 0.0))

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
        duration = float(step.get("duration_sec", 3.0))
        elapsed = time.time() - self._step_start_time

        if elapsed >= duration:
            print(f"[MissionEngine] ✅ TAKE_IMAGE selesai!")
            self._advance_step()
            return self.update_frame(frame, gate_x, detected_balls)

        return 0.0, 0.0, "TAKE_IMAGE"

    def _handle_hold(self, step, frame, gate_x, detected_balls=None):
        """Handle HOLD step."""
        duration = float(step.get("duration_sec", 5.0))
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
        speed_mps          = float(step.get("speed_mps", 0.5))
        heading_offset_deg = float(step.get("heading_offset_deg", 0.0))
        duration_sec       = float(step.get("duration_sec", 5.0))

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
        duration_sec         = float(step.get("duration_sec", 15.0))
        min_runtime_sec      = float(step.get("min_runtime_sec", 1.5))
        heading_kp           = float(step.get("heading_kp", 0.03))
        heading_deadzone_deg = float(step.get("heading_deadzone_deg", 2.0))

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
        turn_angle_deg = float(step.get("turn_angle_deg", 90.0))
        turn_rate_dps  = float(step.get("turn_rate_dps", 20.0))

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
        steer       = max(-1.0, min(1.0, float(step.get("steer", 0.0))))
        throttle    = max(0.0, min(1.0, float(step.get("throttle", 0.3))))
        duration_sec = float(step.get("duration_sec", 3.0))

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

        Aturan transisi lean:
          - Bola kiri (merah) hilang duluan → kapal condong ke KIRI  (steer negatif)
          - Bola kanan (hijau) hilang duluan → kapal condong ke KANAN (steer positif)
          - Kedua bola hilang                → pasangan CLEARED, lanjut ke pasangan berikutnya

        Aturan bola tunggal saat SEARCHING (TIDAK ADA pasangan valid terbentuk —
        entah cuma 1 warna terdeteksi, ATAU dua warna ada tapi gagal lolos safeguard
        rasio-area/lebar-maksimum di sort_ball_pairs, lihat _pick_single_ball_candidate):
        kapal TIDAK mengejar/menyejajarkan diri ke bola terbesar yang ada, melainkan
        MENJAGA JARAK-nya terhadap titik tengah kamera (lihat
        _compute_single_ball_avoid_steer()) — koreksi MENJAUH dari sisi bola,
        sebanding dengan seberapa dekat bola ke tengah frame:
          - Bola hijau (kanan) jadi target hindar → kapal condong ke KIRI
          - Bola merah (kiri)  jadi target hindar → kapal condong ke KANAN

        Format step:
          { "type": "SEQUENTIAL_BUOY", "throttle": 0.4, "ignore_area_px2": 4000,
            "no_detection_finish_sec": 15.0, "single_ball_clearance_px": 384,
            "single_ball_max_steer": 0.4 }

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
        (384) jika tidak diisi.

        `single_ball_max_steer` (0.0-1.0) opsional — steer maksimum koreksi jaga-jarak
        bola tunggal, dicapai saat bola tepat di tengah frame. Fallback ke
        SEQ_SINGLE_BALL_MAX_STEER (0.4) jika tidak diisi.
        """
        throttle    = self._resolve_step_throttle(step)
        cleared     = self._seq_pairs_cleared
        pair_num    = cleared + 1   # Display: pasangan yang sedang diincar (1-indexed)

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
            # di-LOCK. Opsional per-step, fallback ke SEQ_IGNORE_AREA_PX2 kalau kosong.
            ignore_area_px2 = float(step.get("ignore_area_px2", self.SEQ_IGNORE_AREA_PX2))
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
                self._seq_gate_lock_state  = self.GATE_LOCKED
                self._seq_gate_state_entered_at = time.time()
                self._seq_missing_lost_since = None
                self._seq_blind_search_since = None
                print(f"[SEQ_GATE] SEARCHING → LOCKED "
                      f"(pair {pair_label}, red={self._seq_locked_red_pos}, "
                      f"green={self._seq_locked_green_pos})")
                locked_mid_x = (self._seq_locked_red_pos[0] + self._seq_locked_green_pos[0]) // 2
                steer = self.tracking_controller.compute_normalized_steering(locked_mid_x)
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
                    ball, side = single
                    self._seq_blind_search_since = None
                    steer = self._compute_single_ball_avoid_steer(ball, side, step)
                    label = (f"SEQ_GATE:SEARCHING (single {side}, avoid) steer={steer:+.2f} "
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
                    no_detection_finish_sec = float(
                        step.get("no_detection_finish_sec", self.SEQ_NO_DETECTION_FINISH_SEC))
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
            now = time.time()
            locked_duration = now - self._seq_gate_state_entered_at
            if locked_duration > self.GATE_LOCKED_TIMEOUT_SEC and red_visible_locked and green_visible_locked:
                print(f"[SEQ_GATE] LOCKED TIMEOUT ({locked_duration:.1f}s) → SEARCHING (pair {pair_label})")
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
                label = f"SEQ_GATE:LOCKED | SEQUENTIAL_BUOY (pair {pair_label})"
                return steer, throttle, label

            elif not red_visible_locked and green_visible_locked:
                # ★ Bola MERAH (kiri) hilang duluan → condong ke KIRI
                self._seq_missing_side      = "left"
                self._seq_gate_lock_state   = self.GATE_TRANSITIONING
                self._seq_gate_state_entered_at = time.time()
                self._seq_missing_lost_since = None  # bola hijau tersisa baru saja, belum "hilang"
                self._seq_locked_green_pos  = (nearest_green[0], nearest_green[1])
                self._seq_locked_green_area = self._bbox_area(nearest_green)
                # Steer PAKSA konstan ke KIRI — pertahankan sampai bola hijau juga hilang.
                self._seq_transition_steer = -self.TRANSITION_LEAN_MAGNITUDE
                print(f"[SEQ_GATE] LOCKED → TRANSITIONING "
                      f"(pair {pair_label}, missing=LEFT/red, lean={self._seq_transition_steer:+.2f})")
                label = f"SEQ_GATE:TRANSITIONING(←) | SEQUENTIAL_BUOY (pair {pair_label})"
                return self._seq_transition_steer, throttle, label

            elif red_visible_locked and not green_visible_locked:
                # ★ Bola HIJAU (kanan) hilang duluan → condong ke KANAN
                self._seq_missing_side      = "right"
                self._seq_gate_lock_state   = self.GATE_TRANSITIONING
                self._seq_gate_state_entered_at = time.time()
                self._seq_missing_lost_since = None  # bola merah tersisa baru saja, belum "hilang"
                self._seq_locked_red_pos    = (nearest_red[0], nearest_red[1])
                self._seq_locked_red_area   = self._bbox_area(nearest_red)
                # Steer PAKSA konstan ke KANAN — pertahankan sampai bola merah juga hilang.
                self._seq_transition_steer = self.TRANSITION_LEAN_MAGNITUDE
                print(f"[SEQ_GATE] LOCKED → TRANSITIONING "
                      f"(pair {pair_label}, missing=RIGHT/green, lean={self._seq_transition_steer:+.2f})")
                label = f"SEQ_GATE:TRANSITIONING(→) | SEQUENTIAL_BUOY (pair {pair_label})"
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

            if self._seq_missing_side == "left":
                # Bola merah sudah hilang → tunggu bola hijau juga hilang
                nearest_green = self._find_nearest_ball(
                    detected_balls.get("green", []), self._seq_locked_green_pos,
                    self._seq_locked_green_area, self.SEQ_AREA_CONTINUITY_MIN_RATIO,
                    max_dist_px=self.SEQ_IDENTITY_MAX_DIST_PX)
                if nearest_green:
                    remaining_found_this_frame = True
                    self._seq_locked_green_pos = (nearest_green[0], nearest_green[1])
                    self._seq_locked_green_area = self._bbox_area(nearest_green)
                    # Steer tetap PAKSA konstan ke KIRI selama bola hijau masih terlihat.
                    self._seq_transition_steer = -self.TRANSITION_LEAN_MAGNITUDE

            elif self._seq_missing_side == "right":
                # Bola hijau sudah hilang → tunggu bola merah juga hilang
                nearest_red = self._find_nearest_ball(
                    detected_balls.get("red", []), self._seq_locked_red_pos,
                    self._seq_locked_red_area, self.SEQ_AREA_CONTINUITY_MIN_RATIO,
                    max_dist_px=self.SEQ_IDENTITY_MAX_DIST_PX)
                if nearest_red:
                    remaining_found_this_frame = True
                    self._seq_locked_red_pos = (nearest_red[0], nearest_red[1])
                    self._seq_locked_red_area = self._bbox_area(nearest_red)
                    # Steer tetap PAKSA konstan ke KANAN selama bola merah masih terlihat.
                    self._seq_transition_steer = self.TRANSITION_LEAN_MAGNITUDE

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
            transitioning_duration = now - self._seq_gate_state_entered_at
            if transitioning_duration > self.SEQ_TRANSITIONING_SAFETY_TIMEOUT_SEC:
                print(f"[SEQ_GATE] ⚠️ TRANSITIONING SAFETY TIMEOUT ({transitioning_duration:.1f}s) "
                      f"→ CLEARED (pair {pair_label}, paksa — bola tersisa tak kunjung hilang)")
                self._seq_gate_lock_state = self.GATE_CLEARED
                return self._handle_seq_gate_cleared(pair_num)

            # Bola tersisa masih ada di frame (atau baru hilang tapi belum confirmed) →
            # pertahankan manuver condong adaptif / last-known trajectory.
            lean_dir = "←" if self._seq_missing_side == "left" else "→"
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
        self._seq_missing_side          = None
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
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _reset_gate_state_machine(self):
        """Reset semua variabel Gate State Machine ke kondisi awal (SEARCHING)."""
        self._gate_lock_state      = self.GATE_SEARCHING
        self._locked_red_pos       = None
        self._locked_green_pos     = None
        self._missing_side         = None
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

        Return (ball, side) — side "red" atau "green" — atau None kalau tidak ada
        bola sama sekali atau semuanya di bawah min_area_px2 (caller jatuh ke
        fallback gate_x / blind).
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
        best_ball, best_side = max(candidates, key=lambda c: self._bbox_area(c[0]))
        if self._bbox_area(best_ball) >= min_area_px2:
            return best_ball, best_side
        return None

    def _compute_single_ball_avoid_steer(self, ball: Tuple, side: str, step: Dict) -> float:
        """
        Hitung steer untuk MENJAGA JARAK dari satu-satunya bola yang terlihat
        terhadap titik tengah kamera — bukan mengejar/menyejajarkan diri dengannya
        (lihat catatan SEQ_SINGLE_BALL_CLEARANCE_PX).

        side="green" (marker kanan gerbang) terlihat sendirian → kapal harus lewat
        di SEBELAH KIRI-nya → koreksi ke KIRI (steer negatif) saat bola terlalu
        dekat ke tengah frame.
        side="red" (marker kiri gerbang) terlihat sendirian → kebalikannya, koreksi
        ke KANAN (steer positif).

        Magnitude koreksi proporsional terhadap seberapa dekat bola ke tengah frame
        saat ini (urgency 1.0 = bola tepat di tengah/paling bahaya, 0.0 = bola sudah
        >= clearance_px dari tengah/aman, tidak perlu koreksi).
        """
        clearance_px = float(step.get("single_ball_clearance_px", self.SEQ_SINGLE_BALL_CLEARANCE_PX))
        max_steer = float(step.get("single_ball_max_steer", self.SEQ_SINGLE_BALL_MAX_STEER))

        center_x = self.tracking_controller.center_x
        offset_from_center = abs(ball[0] - center_x)

        if clearance_px <= 0:
            return 0.0
        urgency = max(0.0, min(1.0, (clearance_px - offset_from_center) / clearance_px))

        away_direction = -1.0 if side == "green" else 1.0
        return away_direction * urgency * max_steer

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
            try:
                return max(0.0, min(1.0, float(step_throttle)))
            except (TypeError, ValueError):
                pass
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
