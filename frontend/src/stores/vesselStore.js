import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { KMH_PER_KNOT } from "@/utils/geotag";

// Kapal mengirim kecepatan dalam METER/DETIK — itu satuan asli `ground_speed`
// MAVLink, dan sengaja dibiarkan SI di jalur telemetri & blackbox.
// Seluruh tampilan di aplikasi ini berlabel KNOT (Dashboard, GridMap,
// TelemetryChart, SpeedGauge), jadi konversinya dilakukan SEKALI di sini — di batas
// masuk data — bukan diulang di tiap komponen.
//
// Sebelum ini nilai m/s ditampilkan apa adanya di bawah label "KNOTS", sehingga
// setiap angka kecepatan di seluruh aplikasi terbaca ~1,94x lebih kecil dari yang
// sebenarnya (2 m/s tampil "2.00 KNOTS", padahal 3,89 knot).
const MS_TO_KNOTS = 1.94384;

export const useVesselStore = defineStore("vessel", () => {
  // Telemetry State
  const lat = ref(-7.9215169);
  const lng = ref(112.5973649);
  const heading = ref(0);
  const sog = ref(0); // Speed Over Ground, KNOT (dikonversi dari m/s di updateTelemetry)
  // Course Over Ground: arah GERAK kapal sesungguhnya (dari vektor kecepatan GPS),
  // beda dari `heading` yang menunjukkan ke mana haluan menghadap. Selisih keduanya
  // memperlihatkan hanyutan arus/angin. Satuan 0-360° (konvensi maritim), TIDAK
  // dinormalisasi ke -180..180 seperti heading di bawah.
  const cog = ref(0);
  // false = kapal terlalu pelan untuk punya arah gerak yang berarti; `cog` masih
  // berisi nilai valid terakhir, jadi jangan ditampilkan sebagai angka terkini.
  const cogValid = ref(false);

  /**
   * COG sah TERAKHIR yang pernah dilihat base station, dan kapan.
   *
   * null = kapal belum pernah sekali pun bergerak cukup cepat sejak halaman ini
   * dibuka. Bedanya penting: `cog` sendiri lahir bernilai 0 dan tetap 0 selama
   * kapal belum pernah jalan, jadi memampangnya apa adanya akan menyatakan
   * "kapal mengarah ke UTARA" — arah yang tidak pernah diukur siapa pun.
   *
   * Disalin di sini, TIDAK diambil dari `cog` milik kapal, supaya kapal yang
   * restart (nilainya kembali 0) tidak membuat nol itu tampil seolah-olah arah
   * terakhir yang teramati.
   */
  const cogTertahan = ref(null);
  let cogSahAt = 0;
  /**
   * Umur nilai tertahan, diperbarui tiap telemetri masuk — bukan oleh timer.
   *
   * Telemetri datang ~10x per detik, jadi angkanya tetap hidup di layar; dan
   * saat telemetri BERHENTI, umurnya ikut membeku. Itu memang yang benar:
   * kalau kabar dari kapal sudah putus, base station tidak tahu apa pun tentang
   * "sekarang", dan jam yang terus berjalan hanya akan mengarang kepastian.
   */
  const cogUmurMs = ref(0);

  const pitch = ref(0);
  const roll = ref(0);
  const yaw = ref(0);

  const batteryPct = ref(100);
  const batteryVolt = ref(12.6);

  const gpsFix = ref(0); // 0: No Fix, 1: 2D, 2: 3D, 3: DGPS, 4: RTK
  const satellites = ref(0);
  // HDOP horizontal (meter) dari GPS_RAW_INT. 0 = belum diketahui.
  const gpsHdop = ref(0);

  // Lintasan arena yang BENAR-BENAR berlaku di kapal ("A" | "B"). Datang lewat
  // telemetri, bukan disimpan dari apa yang dikira sudah terkirim — kapal bisa
  // menolak perintahnya (mis. saat misi berjalan).
  const track = ref("B");

  // Kamera bawah air: terpasang (ada di .env kapal) vs benar-benar memberi frame.
  // Dipisah karena keduanya butuh tindakan berbeda — yang satu memasang kamera,
  // yang lain memeriksa kabel.
  const underwaterFitted = ref(false);
  const underwaterOk = ref(false);

  // Posisi FISIK switch sumber kendali di remote ("minipc" | "remote" | null).
  // Dilaporkan terpisah dari manualSource karena keduanya BOLEH berbeda: sumber
  // kendali bisa diubah dari dashboard, dan switch baru merebutnya kembali saat
  // digerakkan. Selisihnya harus terlihat operator, bukan disembunyikan.
  const rcSwitchPosition = ref(null);
  const signalStrength = ref(0);

  // Flight Controller Status (dari Pixhawk via MAVLink)
  const isConnected = ref(false);  // Pixhawk terdeteksi & heartbeat aktif
  const isArmed = ref(false);      // Motor sudah ARM
  const mode = ref('UNKNOWN');     // Mode aktif: MANUAL, GUIDED, AUTO, dll

  // Sumber kendali manual: 'minipc' (mini PC di kapal) atau 'remote' (remote RC fisik).
  // Saat 'remote', Mini PC memblokir SEMUA perintah geraknya sendiri supaya stik remote
  // benar-benar pegang kendali — jadi joystick/keyboard di halaman ini ikut nonaktif.
  const manualSource = ref('minipc');

  // Apakah sumber kendali sedang ditentukan SWITCH FISIK di remote (mis. SwD pada
  // FS-i6X). Saat true, posisi switch selalu menang dan tombol pemilih di dashboard
  // hanya indikator — menekannya akan dikembalikan kapal dalam sepersekian detik.
  const rcSourceSwitch = ref(false);
  const rcSourceChannel = ref(0);

  // Geofence yang BENAR-BENAR berlaku di kapal (bukan yang tersimpan di DB).
  // Peta menggambar lingkarannya dari sini supaya yang terlihat selalu mewakili
  // keadaan sebenarnya, bukan yang dikira sudah terkirim.
  const geofenceEnabled = ref(false);
  const geofenceLat = ref(0);
  const geofenceLon = ref(0);
  const geofenceRadiusM = ref(0);

  // Video Recording State (Tanpa Object Detection)
  const isRecording = ref(false);
  const recordingFilename = ref('');
  const recordingResolution = ref('640x480');

  // Streaming ON/OFF State
  // true = encode + upload aktif (default); false = hemat CPU/bandwidth
  const isStreaming = ref(true);

  // Camera & Connectivity State
  const cameraConnected = ref(false);  // Apakah stream kamera aktif
  const asvConnected = ref(false);     // Apakah Mini PC (ASV) terkoneksi ke base station

  // System Warnings (dari backend atau deteksi lokal)
  // Format: { id, level, code, message, timestamp }
  const warnings = ref([]);

  // Advanced Navigation Data
  const xte = ref(0);
  const dtw = ref(0);
  const nextWp = ref(0);

  // Engine Stats
  const thrusterL = ref(0);
  const thrusterR = ref(0);
  const rpmL = ref(0);
  const rpmR = ref(0);

  // Computed Properties
  // Lembar ketentuan meminta SOG ditampilkan dalam knot DAN km/jam. Diturunkan dari
  // `sog` (knot) agar tidak ada dua sumber angka kecepatan yang bisa berbeda.
  const sogKmh = computed(() => sog.value * KMH_PER_KNOT);
  const isGpsValid = computed(() => gpsFix.value >= 2);

  // ── COG yang tetap terbaca saat kapal pelan atau diam ─────────────────────
  //
  // Dulu seluruh tampilan menulis "—" begitu cog_valid jatuh, dan itu berarti
  // COG menghilang justru pada dua keadaan paling sering: kapal menunggu di
  // dermaga, dan kapal merayap saat manuver presisi. Operator kehilangan satu-
  // satunya angka yang memberitahu ARAH GERAK sesungguhnya, padahal arah itu
  // tidak berubah hanya karena kapal berhenti.
  //
  // Yang TIDAK dilakukan: menghitung ulang COG dari derau. Di bawah 0,3 m/s
  // vektor kecepatan GPS melompat acak ke segala penjuru (lihat
  // COG_MIN_SPEED_MS di core/state.py kapal), jadi memampangkannya sebagai
  // angka terkini justru memberi arah yang salah dengan percaya diri.
  //
  // Yang dilakukan: pampang arah sah TERAKHIR, sebut umurnya, dan katakan
  // bahwa itu tertahan. Operator dapat angka yang berarti, tanpa mengira
  // angka itu hidup.

  /** Angka yang layak dipampang: yang hidup kalau ada, kalau tidak yang tertahan. */
  const cogTampil = computed(() => (cogValid.value ? cog.value : cogTertahan.value));

  /** Ada sesuatu untuk dipampang? false = kapal belum pernah bergerak. */
  const cogAda = computed(() => cogTampil.value !== null);

  /** Angka yang dipampang bukan pengukuran terkini. */
  const cogTertahanTampil = computed(() => cogAda.value && !cogValid.value);

  /**
   * Keterangan di bawah angka COG. Satu tempat, supaya kelima tampilan yang
   * memampang COG tidak menjelaskan hal yang sama dengan kalimat berbeda-beda.
   */
  const cogKeterangan = computed(() => {
    if (cogValid.value) return "";
    if (!cogAda.value) return "kapal belum pernah bergerak";
    const detik = Math.round(cogUmurMs.value / 1000);
    if (detik < 60) return `tertahan — ${detik} d lalu`;
    const menit = Math.round(detik / 60);
    if (menit < 60) return `tertahan — ${menit} mnt lalu`;
    return `tertahan — ${Math.floor(menit / 60)} j ${menit % 60} mnt lalu`;
  });
  const batteryColor = computed(() => {
    if (batteryPct.value > 50) return "text-success";
    if (batteryPct.value > 20) return "text-warning";
    return "text-danger";
  });

  // Actions to update telemetry
  /**
   * Field telemetri yang PERNAH benar-benar dikirim kapal.
   *
   * Beberapa pembacaan di halaman Monitoring dan Juri (XTE, jarak ke waypoint,
   * RPM, thruster) tidak pernah dikirim kapal sama sekali — nilainya bukan
   * "nol", melainkan TIDAK ADA. Menampilkannya sebagai 0 membuat juri membaca
   * "RPM 0" dan "Thruster 0 %" sebagai kapal yang mati, atau sebagai ukuran
   * yang sah padahal tidak pernah diukur.
   *
   * Dengan penanda ini, tampilannya bisa menulis "—" untuk yang belum ada, dan
   * otomatis menyala sendiri kalau nanti kapal mulai mengirimnya.
   */
  const fieldDiterima = ref(new Set());

  /** True kalau kapal pernah benar-benar mengirim field ini. */
  const punyaData = (nama) => fieldDiterima.value.has(nama);

  function updateTelemetry(data) {
    // Pesan TELEMETRY tanpa payload akan melempar di baris-baris `data.x` di
    // bawah, DI DALAM penangan onmessage WebSocket — pesan itu hilang beserta
    // segala yang mestinya diproses sesudahnya. Dijaga di sini, satu tempat.
    if (!data || typeof data !== "object") return;

    const belumTercatat = Object.keys(data).filter(
      (k) => data[k] !== undefined && data[k] !== null && !fieldDiterima.value.has(k)
    );
    // Set diganti, bukan dimutasi: mutasi tidak memicu reaktivitas Vue. Hanya
    // terjadi pada beberapa pesan pertama, jadi ongkosnya tidak berarti.
    if (belumTercatat.length) {
      fieldDiterima.value = new Set([...fieldDiterima.value, ...belumTercatat]);
    }

    // Number.isFinite, bukan `!== undefined`: saat kapal belum punya fix, kapal
    // mengirim lat/lng bernilai null, dan `null !== undefined && null !== 0`
    // dua-duanya benar — posisi kapal jadi null, penanda di peta hilang, dan
    // setiap perhitungan jarak menghasilkan NaN tanpa satu pun pesan error.
    if (Number.isFinite(data.lat) && data.lat !== 0) lat.value = data.lat;
    if (Number.isFinite(data.lng) && data.lng !== 0) lng.value = data.lng;

    if (data.heading !== undefined) {
      heading.value = data.heading;
      if (heading.value > 180) {
        heading.value -= 360;
      } else if (heading.value < -180) {
        heading.value += 360;
      }
    }
    // data.sog dari kapal bersatuan m/s — lihat MS_TO_KNOTS di atas.
    if (data.sog !== undefined) sog.value = data.sog * MS_TO_KNOTS;
    if (data.cog !== undefined && data.cog !== null) cog.value = data.cog;
    if (data.cog_valid !== undefined) cogValid.value = data.cog_valid;
    // Tangkap arah gerak SELAGI masih sah. Inilah satu-satunya kesempatan:
    // begitu kapal melambat, angka yang sama tidak akan pernah ditandai sah lagi.
    if (cogValid.value && Number.isFinite(cog.value)) {
      cogTertahan.value = cog.value;
      cogSahAt = Date.now();
    }
    if (cogTertahan.value !== null) cogUmurMs.value = Date.now() - cogSahAt;
    if (data.pitch !== undefined) pitch.value = data.pitch;
    if (data.roll !== undefined) roll.value = data.roll;
    if (data.yaw !== undefined) yaw.value = data.yaw;
    if (data.battery_pct !== undefined) batteryPct.value = data.battery_pct;
    if (data.battery_volt !== undefined) batteryVolt.value = data.battery_volt;
    if (data.gps_fix !== undefined) gpsFix.value = data.gps_fix;
    if (data.satellites !== undefined) satellites.value = data.satellites;
    if (Number.isFinite(data.gps_hdop)) gpsHdop.value = data.gps_hdop;
    if (data.track) track.value = String(data.track).toUpperCase();
    if (data.underwater_camera_fitted !== undefined) underwaterFitted.value = !!data.underwater_camera_fitted;
    if (data.underwater_camera_connected !== undefined) underwaterOk.value = !!data.underwater_camera_connected;
    if (data.rc_source_switch_position !== undefined) rcSwitchPosition.value = data.rc_source_switch_position;
    if (data.signal_strength !== undefined) signalStrength.value = data.signal_strength;

    // Advanced Nav & Engines
    if (data.dtw !== undefined) dtw.value = data.dtw;
    if (data.xte !== undefined) xte.value = data.xte;
    if (data.next_wp !== undefined) nextWp.value = data.next_wp;
    if (data.thruster_l !== undefined) thrusterL.value = data.thruster_l;
    if (data.thruster_r !== undefined) thrusterR.value = data.thruster_r;
    if (data.rpm_l !== undefined) rpmL.value = data.rpm_l;
    if (data.rpm_r !== undefined) rpmR.value = data.rpm_r;

    // Status Pixhawk & Kamera
    if (data.is_connected !== undefined) isConnected.value = data.is_connected;
    if (data.is_armed !== undefined) isArmed.value = data.is_armed;
    if (data.mode !== undefined) mode.value = data.mode;
    if (data.manual_source !== undefined) manualSource.value = data.manual_source;
    if (data.rc_source_switch !== undefined) rcSourceSwitch.value = data.rc_source_switch;
    if (data.rc_source_channel !== undefined) rcSourceChannel.value = data.rc_source_channel;
    if (data.geofence_enabled !== undefined) geofenceEnabled.value = data.geofence_enabled;
    if (data.geofence_lat !== undefined) geofenceLat.value = data.geofence_lat;
    if (data.geofence_lon !== undefined) geofenceLon.value = data.geofence_lon;
    if (data.geofence_radius_m !== undefined) geofenceRadiusM.value = data.geofence_radius_m;
    if (data.camera_connected !== undefined) cameraConnected.value = data.camera_connected;
    // Status Recording Video Mentah
    if (data.is_recording !== undefined) isRecording.value = data.is_recording;
    if (data.recording_filename !== undefined) recordingFilename.value = data.recording_filename;
    if (data.recording_resolution !== undefined) recordingResolution.value = data.recording_resolution;
    // Status Streaming ON/OFF
    if (data.is_streaming !== undefined) isStreaming.value = data.is_streaming;
  }


  /**
   * Tambahkan warning ke antrian.
   * @param {string} level - 'critical' | 'warning' | 'info'
   * @param {string} code  - kode unik, misal 'CAMERA_LOST'
   * @param {string} message - pesan human-readable
   */
  function addWarning(level, code, message) {
    // Jika warning dengan code yang sama sudah ada, update timestamp-nya saja
    const existing = warnings.value.find(w => w.code === code);
    if (existing) {
      existing.timestamp = Date.now();
      existing.message = message;
      return;
    }
    warnings.value.unshift({
      id: `${code}_${Date.now()}`,
      level,
      code,
      message,
      timestamp: Date.now(),
    });
    // Batasi maksimal 10 warning
    if (warnings.value.length > 10) warnings.value.pop();
  }

  /** Hapus warning berdasarkan code */
  function clearWarning(code) {
    warnings.value = warnings.value.filter(w => w.code !== code);
  }

  /** Hapus semua warning */
  function clearAllWarnings() {
    warnings.value = [];
  }

  return {
    lat, lng, heading, sog, cog, cogValid,
    cogTampil, cogAda, cogTertahanTampil, cogKeterangan, cogUmurMs,
    pitch, roll, yaw,
    batteryPct, batteryVolt,
    gpsFix, satellites, gpsHdop, signalStrength, track,
    underwaterFitted, underwaterOk, rcSwitchPosition,
    punyaData,
    xte, dtw, nextWp,
    thrusterL, thrusterR, rpmL, rpmR,
    isConnected, isArmed, mode, manualSource, rcSourceSwitch, rcSourceChannel,
    geofenceEnabled, geofenceLat, geofenceLon, geofenceRadiusM,
    isRecording, recordingFilename, recordingResolution,
    isStreaming,
    cameraConnected, asvConnected,
    warnings,
    isGpsValid, batteryColor, sogKmh,
    updateTelemetry,
    addWarning, clearWarning, clearAllWarnings,
  };
});

