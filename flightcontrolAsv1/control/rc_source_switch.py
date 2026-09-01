"""
Pemindah sumber kendali dari SWITCH FISIK di remote (mis. SwD pada FlySky FS-i6X).

Sebelum modul ini, satu-satunya cara menyerahkan kemudi ke remote adalah menekan
tombol di dashboard. Itu bermasalah justru di saat paling dibutuhkan: kapal kabur
atau mau menabrak, dan orang yang memegang remote harus meneriakkan permintaan ke
orang lain yang memegang laptop. Sekarang tuas itu ada di tangan yang sama dengan
stiknya.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DUA KEPUTUSAN PERILAKU YANG PENTING

1. POSISI SWITCH SELALU MENANG selama sinyal RC hidup.
   Watcher ini membandingkan posisi switch dengan sumber kendali aktif SETIAP
   putaran, bukan cuma saat switch digerakkan. Jadi kalau seseorang menekan tombol
   di web sementara SwD ada di posisi REMOTE, sumbernya kembali ke REMOTE dalam
   sepersekian detik.

   Sengaja begitu: tuas darurat harus berarti apa yang terlihat. Kalau switch hanya
   bertindak saat digerakkan, SwD bisa terlihat di posisi REMOTE padahal kapal
   sebenarnya di MINI PC karena ada yang mengklik web — dan operator baru sadar saat
   stiknya ternyata tidak menggerakkan apa pun.

2. SINYAL RC HILANG → PERTAHANKAN SUMBER TERAKHIR, jangan pindah sendiri.
   Memaksa ke MINI PC saat sinyal hilang berarti kapal MULAI BERGERAK SENDIRI persis
   ketika operator kehilangan kendali fisiknya — kebalikan dari yang diinginkan.
   Memaksa ke REMOTE juga tidak menolong: tidak ada yang bisa mengemudi kalau
   sinyalnya memang hilang.

   Jadi watcher diam, mengirim peringatan ke base station, dan menyerahkan urusan ke
   RC failsafe ArduPilot di sisi Flight Controller — yang memang dirancang untuk itu
   dan bekerja walau mini PC sekalipun mati.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MENYIAPKAN FS-i6X:
  1. Di remote: menu Functions → Aux. channels → pilih channel (mis. Ch 8),
     set sumbernya ke SwD.
  2. Pastikan channel itu benar-benar sampai ke Pixhawk: di Mission Planner lihat
     Radio Calibration, gerakkan SwD, bar channel-nya harus ikut bergerak.
  3. Isi ASV_RC_SOURCE_CHANNEL di flightcontrolAsv1/.env dengan nomor channel itu.

Tanpa ASV_RC_SOURCE_CHANNEL, modul ini TIDAK aktif sama sekali — fiturnya opt-in
supaya switch yang belum dikonfigurasi tidak diam-diam mengunci kendali.
"""

import os
import threading
import time

from control import manual_source


class RCSourceSwitch:
    """Pantau satu channel RC dan samakan sumber kendali dengan posisi switch-nya."""

    # Ambang PWM dengan pita mati di tengah (histeresis). Nilai di ANTARA kedua
    # ambang tidak mengubah apa pun — posisi sebelumnya dipertahankan. Ini yang
    # membuat switch 3-posisi (mis. SwC) juga bisa dipakai: posisi tengah = "jangan
    # ubah", dan yang lebih penting, jitter beberapa mikrodetik di sekitar titik
    # tengah tidak membuat kendali berkedip antara dua sumber.
    PWM_HIGH = 1700
    PWM_LOW = 1300

    # Posisi harus stabil selama ini sebelum ditindaklanjuti. Satu paket RC yang
    # rusak tidak boleh memindahkan kendali kapal.
    CONFIRM_SEC = 0.3

    # Paket RC lebih tua dari ini dianggap sinyal hilang. ArduPilot mengirim
    # RC_CHANNELS pada laju stream (10 Hz di sini), jadi 1,5 detik sudah longgar.
    STALE_SEC = 1.5

    POLL_SEC = 0.1

    def __init__(self, asv, channel: int = None, invert: bool = None,
                 on_change=None, on_warning=None):
        """
        :param asv: ASVController.
        :param channel: nomor channel RC (1-18). None/0 = fitur nonaktif.
        :param invert: False (default) = PWM TINGGI berarti REMOTE. True membalik.
        :param on_change: callback(sumber_baru: str) setelah perpindahan berhasil.
        :param on_warning: callback(level, code, message) untuk dikirim ke base station.
        """
        self.asv = asv
        if channel is None:
            channel = int(os.getenv("ASV_RC_SOURCE_CHANNEL", "0") or 0)
        if invert is None:
            invert = os.getenv("ASV_RC_SOURCE_INVERT", "0").strip().lower() in ("1", "true", "yes")
        self.channel = int(channel)
        self.invert = bool(invert)
        self._on_change = on_change
        self._on_warning = on_warning

        self._is_running = False
        self._thread = None

        # Posisi switch yang sedang dinilai, dan sejak kapan dinilai.
        self._posisi_kandidat = None
        self._kandidat_sejak = 0.0
        # Posisi yang sudah lolos debounce dan dipakai sebagai kehendak operator.
        self._posisi_stabil = None
        self._link_hidup = None      # None = belum pernah dinilai

    @property
    def enabled(self) -> bool:
        return self.channel > 0

    def start(self):
        if self._is_running:
            return
        if not self.enabled:
            print("[RCSource] Switch sumber kendali dari remote NONAKTIF "
                  "(ASV_RC_SOURCE_CHANNEL belum diisi).")
            return
        self._is_running = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="RCSourceSwitchThread")
        self._thread.start()
        arah = "PWM RENDAH" if self.invert else "PWM TINGGI"
        print(f"[RCSource] Aktif — channel {self.channel}, {arah} = REMOTE RC. "
              f"Posisi switch selalu menang selama sinyal RC hidup.")

    def stop(self):
        self._is_running = False

    # ------------------------------------------------------------------ #

    def _loop(self):
        while self._is_running:
            try:
                self._tick()
            except Exception as e:
                print(f"[RCSource] Error saat membaca switch: {e}")
            time.sleep(self.POLL_SEC)

    def _tick(self):
        sekarang = time.time()
        segar = self.asv.state.rc_link_fresh(self.STALE_SEC)
        pwm = self.asv.state.get_rc_channel(self.channel) if segar else None

        # --- Sinyal RC hilang / channel tidak terbaca ---
        if pwm is None:
            if self._link_hidup is not False:
                self._link_hidup = False
                aktif = self.asv.get_manual_source()
                self._warn(
                    "warning", "RC_LINK_LOST",
                    f"Sinyal RC hilang — posisi switch tidak terbaca. Sumber kendali "
                    f"DIPERTAHANKAN di {manual_source.label(aktif)}; RC failsafe "
                    f"Flight Controller yang mengambil alih dari sini.")
            # Debounce dilupakan supaya saat sinyal kembali, posisinya dinilai ulang
            # dari nol — bukan melanjutkan hitungan dari sebelum sinyal putus.
            self._posisi_kandidat = None
            return

        if self._link_hidup is not True:
            self._link_hidup = True
            self._warn("info", "RC_LINK_OK",
                       "Sinyal RC terbaca — switch sumber kendali aktif kembali.")

        # --- Terjemahkan PWM ke posisi, dengan pita mati di tengah ---
        if pwm >= self.PWM_HIGH:
            posisi = manual_source.MINIPC if self.invert else manual_source.REMOTE
        elif pwm <= self.PWM_LOW:
            posisi = manual_source.REMOTE if self.invert else manual_source.MINIPC
        else:
            return   # zona mati — pertahankan posisi stabil sebelumnya

        # --- Debounce: posisi harus bertahan CONFIRM_SEC ---
        if posisi != self._posisi_kandidat:
            self._posisi_kandidat = posisi
            self._kandidat_sejak = sekarang
            return
        if (sekarang - self._kandidat_sejak) < self.CONFIRM_SEC:
            return

        if posisi != self._posisi_stabil:
            self._posisi_stabil = posisi
            print(f"[RCSource] 🎛️ Switch remote → {manual_source.label(posisi)} "
                  f"(ch{self.channel}={pwm}us)")

        # --- Posisi switch selalu menang: samakan kalau berbeda ---
        # Dibandingkan tiap putaran, bukan cuma saat switch bergerak. Itulah yang
        # mengembalikan kendali kalau ada yang mengubahnya dari web.
        if self.asv.get_manual_source() != posisi:
            ok = self.asv.set_manual_source(posisi)
            if ok:
                self._warn(
                    "info", "RC_SOURCE_SWITCHED",
                    f"Sumber kendali dipindah ke {manual_source.label(posisi)} "
                    f"lewat switch di remote (ch{self.channel}).")
                if self._on_change:
                    try:
                        self._on_change(posisi)
                    except Exception as e:
                        print(f"[RCSource] Error pada callback perpindahan: {e}")

    def _warn(self, level: str, code: str, message: str):
        """
        Kirim peringatan ke base station. TIDAK dibatasi laju — dan itu disengaja.

        Versi pertama modul ini membatasi peringatan sinyal RC ke satu per 15 detik.
        Terbukti salah saat diuji: karena RC_LINK_OK dan RC_LINK_LOST berbagi jatah
        yang sama, sinyal yang putus-nyambung hanya terlaporkan SEKALI lalu senyap —
        persis kebalikan dari yang dibutuhkan, karena link yang berkedip justru
        keadaan paling perlu diketahui operator.

        Membanjiri panel bukan risiko di sini: pemanggil hanya memanggil method ini
        saat status BERUBAH (lihat _link_hidup), dan kehilangan sinyal baru diakui
        setelah STALE_SEC. Keduanya sudah membatasi lajunya di bawah satu pasang
        peringatan per 1,5 detik.
        """
        print(f"[RCSource] {code}: {message}")
        if self._on_warning:
            try:
                self._on_warning(level, code, message)
            except Exception as e:
                print(f"[RCSource] Error saat mengirim peringatan: {e}")
