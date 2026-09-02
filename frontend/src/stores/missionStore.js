import { defineStore } from "pinia";
import { ref, computed, onMounted } from "vue";
import { useWebsocketStore } from "./websocketStore";
import { apiUrl } from "@/config/api";
import { authHeaders } from "@/utils/session";

// ─── Step Type Definitions ───────────────────────────────────────────────────
export const STEP_TYPES = [
  {
    type: "START",
    label: "Start / Warmup",
    icon: "⚡",
    color: "text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-500/30",
    fields: [{ key: "duration_sec", label: "Warmup Duration (s)", type: "number", default: 2 }],
  },
  {
    type: "TRACKING_BUOY",
    label: "Tracking Buoy (AI Vision)",
    icon: "🎯",
    color: "text-primary",
    bg: "bg-primary/10 border-primary/30",
    fields: [
      { key: "pass_count", label: "Gate Pass Count", type: "number", default: 1 },
      { key: "throttle", label: "Throttle (0-1)", type: "number", default: 0.4 },
      {
        key: "locked_timeout_area_growth_min_ratio",
        label: "Locked-Timeout Auto-Count Growth (x)",
        type: "number",
        default: 1.5,
        // Kalau kapal LOCKED >8 detik pada pasangan yang sama (kedua bola tidak
        // pernah hilang dari frame), dan area pasangan sudah membesar sebesar
        // rasio ini sejak lock pertama, dihitung sebagai 1 pass otomatis —
        // bukti kapal sudah mendekat/lewat, bukan cuma diam menatap gerbang.
      },
    ],
  },
  {
    type: "GOTO_GPS",
    label: "Go To GPS Coordinate",
    icon: "🧭",
    color: "text-sky-400",
    bg: "bg-sky-500/10 border-sky-500/30",
    fields: [
      { key: "lat", label: "Latitude", type: "number", default: -7.9215169 },
      { key: "lon", label: "Longitude", type: "number", default: 112.5973649 },
    ],
  },
  {
    type: "TAKE_IMAGE",
    label: "Take Image / Record",
    icon: "📷",
    color: "text-violet-400",
    bg: "bg-violet-500/10 border-violet-500/30",
    fields: [{ key: "duration_sec", label: "Duration (s)", type: "number", default: 3 }],
  },
  {
    type: "HOLD",
    label: "Hold Position",
    icon: "⚓",
    color: "text-amber-400",
    bg: "bg-amber-500/10 border-amber-500/30",
    fields: [{ key: "duration_sec", label: "Hold Duration (s)", type: "number", default: 5 }],
  },
  // ── Dynamic Movement Steps ──────────────────────────────────────────────
  {
    type: "CUSTOM_FORWARD",
    label: "Custom Forward (Dynamic)",
    icon: "🚀",
    color: "text-cyan-400",
    bg: "bg-cyan-500/10 border-cyan-500/30",
    fields: [
      {
        key: "heading_offset_deg",
        label: "Heading Offset (°)",
        type: "number",
        default: 0,
        // Sudut kemiringan arah gerak dari haluan kapal.
        // 0 = maju lurus, +N = condong kanan N°/s, -N = condong kiri N°/s.
        // Digunakan sebagai yaw rate konstan (°/s) oleh mission_engine saat send_velocity.
      },
      {
        key: "duration_sec",
        label: "Duration (s)",
        type: "number",
        default: 5,
        // Batas waktu kapal menjalankan misi maju ini (dalam detik).
        // Engine akan advance_step() saat elapsed >= duration_sec.
      },
      {
        key: "speed_mps",
        label: "Speed (m/s)",
        type: "number",
        default: 0.5,
        // Kecepatan maju kapal dalam meter per detik.
        // Dikirim sebagai forward_speed ke NavigationControl.send_velocity().
      },
    ],
  },
  {
    type: "GYRO_FORWARD",
    label: "Gyro Forward (Heading Hold)",
    icon: "🌀",
    color: "text-indigo-400",
    bg: "bg-indigo-500/10 border-indigo-500/30",
    fields: [
      {
        key: "throttle",
        label: "Throttle (0-1)",
        type: "number",
        default: 0.4,
        // Sama seperti TRACKING_BUOY: mode MANUAL, gerak via RC Override. Kosongkan
        // untuk fallback ke throttle global (speed_scheduler.max_base_throttle).
      },
      {
        key: "duration_sec",
        label: "Max Duration (s)",
        type: "number",
        default: 15,
        // Batas waktu MAKSIMUM cruise (safety cap). Step berhenti lebih awal begitu
        // buoy (merah/hijau) terdeteksi kontinu di kamera, mana pun yang lebih dulu.
      },
      {
        key: "min_runtime_sec",
        label: "Min Runtime Before Buoy-Stop (s)",
        type: "number",
        default: 1.5,
        // Deteksi buoy diabaikan sampai kapal sudah maju minimal sekian detik —
        // mencegah step langsung selesai kalau buoy/false-positive kebetulan sudah
        // kelihatan tepat saat step baru mulai (kapal belum sempat maju sama sekali).
      },
      {
        key: "heading_kp",
        label: "Heading Correction Kp",
        type: "number",
        default: 0.03,
        // Gain proporsional: steer_norm (-1..+1) per derajat error heading.
        // Heading target = heading kapal saat step ini dimulai (heading-hold).
      },
      {
        key: "heading_deadzone_deg",
        label: "Heading Deadzone (°)",
        type: "number",
        default: 2,
        // Error heading di bawah nilai ini dianggap lurus — tidak ada koreksi,
        // mencegah kapal bergetar akibat micro-correction.
      },
    ],
  },
  {
    type: "PRECISION_TURN",
    label: "Precision Turning",
    icon: "🔄",
    color: "text-orange-400",
    bg: "bg-orange-500/10 border-orange-500/30",
    fields: [
      {
        key: "turn_angle_deg",
        label: "Turn Angle (°)",
        type: "number",
        default: 90,
        // Sudut total belok yang harus ditempuh kapal.
        // +90 = belok kanan 90°, -90 = belok kiri 90°.
        // Engine menghitung target_heading = initial_heading + turn_angle_deg.
      },
      {
        key: "turn_rate_dps",
        label: "Turn Rate (°/s)",
        type: "number",
        default: 20,
        // Kecepatan rotasi dalam derajat per detik.
        // Dikirim sebagai turn_rate_deg ke NavigationControl.send_velocity() selama maneuver.
      },
    ],
  },
  {
    type: "TIMED_STEER",
    label: "Timed Steer (Manual Mode)",
    icon: "⏱️",
    color: "text-rose-400",
    bg: "bg-rose-500/10 border-rose-500/30",
    fields: [
      {
        key: "steer",
        label: "Steering (-1 kiri, 0 lurus, +1 kanan)",
        type: "number",
        default: 0,
      },
      {
        key: "throttle",
        label: "Throttle (0-1)",
        type: "number",
        default: 0.3,
      },
      {
        key: "duration_sec",
        label: "Duration (s)",
        type: "number",
        default: 3,
      },
    ],
  },
  // ── Timed Steer yang berhenti saat GERBANG terlihat ────────────────────
  // Sama persis dengan TIMED_STEER di atas (steer + throttle konstan lewat RC
  // override di mode MANUAL, murni timer), dengan satu tambahan: step selesai
  // lebih awal begitu bola MERAH dan HIJAU terdeteksi BERSAMAAN. Satu warna saja
  // tidak cukup — satu bola tidak menentukan gerbang mana pun, dan menyerahkan
  // kendali ke step berikutnya berdasarkan itu membuat step buoy-tracking mulai
  // tanpa gerbang utuh untuk dibidik.
  {
    type: "STEER_UNTIL_GATE",
    label: "Timed Steer Until Gate (Manual)",
    icon: "🎯",
    color: "text-fuchsia-400",
    bg: "bg-fuchsia-500/10 border-fuchsia-500/30",
    fields: [
      {
        key: "steer",
        label: "Steering (-1 kiri, 0 lurus, +1 kanan)",
        type: "number",
        default: 0,
      },
      {
        key: "throttle",
        label: "Throttle (0-1)",
        type: "number",
        default: 0.3,
      },
      {
        key: "duration_sec",
        label: "Max Duration (s)",
        type: "number",
        default: 10,
        // Batas waktu MAKSIMUM, bukan durasi tetap: step berhenti lebih awal begitu
        // gerbang ketemu. Isi 0 = tanpa batas waktu — kapal hanya berhenti kalau
        // gerbang terlihat. Hati-hati memakainya.
      },
      {
        key: "min_runtime_sec",
        label: "Min Runtime Before Gate-Stop (s)",
        type: "number",
        default: 1.5,
        // Deteksi gerbang diabaikan sampai kapal sudah bergerak sekian detik.
        // Tanpa ini, kalau gerbang kebetulan sudah terlihat saat step dimulai,
        // step selesai dalam satu frame dan manuvernya tidak pernah terjadi.
      },
      {
        key: "gate_confirm_sec",
        label: "Gate Confirm Duration (s)",
        type: "number",
        default: 0.3,
        // Gerbang harus terlihat TERUS-MENERUS selama ini sebelum step diakhiri —
        // supaya satu frame false-positive YOLO tidak memotong manuver.
      },
      {
        key: "ignore_area_px2",
        label: "Ignore Below Area (px²)",
        type: "number",
        default: 4000,
        // Bola dengan area bounding box di bawah nilai ini TIDAK dihitung sebagai
        // bagian gerbang. Tanpa ambang ini, pantulan air sekecil apa pun yang lolos
        // YOLO sudah cukup mengakhiri step lebih awal.
      },
    ],
  },
  // ── Timed Steer yang berhenti saat BOX terlihat ────────────────────────
  // Kembaran STEER_UNTIL_GATE di atas, tapi yang mengakhiri manuver adalah BOX
  // (biru/hijau), bukan gerbang bola. Gunanya: setelah lintasan buoy selesai,
  // kapal perlu menyapu ke arah area box — dan sapuan itu harus berhenti begitu
  // box masuk pandangan, supaya Photo Box berikutnya mulai dengan target sudah
  // di frame, bukan mencari dari nol.
  //
  // Box dideteksi kamera PERMUKAAN yang sama seperti buoy. Tidak ada kamera
  // underwater di sistem ini.
  {
    type: "STEER_UNTIL_BOX",
    label: "Timed Steer Until Box (Manual)",
    icon: "📦",
    color: "text-blue-400",
    bg: "bg-blue-500/10 border-blue-500/30",
    fields: [
      {
        key: "steer",
        label: "Steering (-1 kiri, 0 lurus, +1 kanan)",
        type: "number",
        default: 0,
      },
      {
        key: "throttle",
        label: "Throttle (0-1)",
        type: "number",
        default: 0.3,
      },
      {
        key: "duration_sec",
        label: "Max Duration (s)",
        type: "number",
        default: 10,
        // Batas waktu MAKSIMUM, bukan durasi tetap: step berhenti lebih awal begitu
        // box ketemu. Isi 0 = tanpa batas waktu — kapal hanya berhenti kalau box
        // terlihat. Hati-hati memakainya.
      },
      {
        key: "target",
        label: "Target (any / blue / green / both)",
        type: "text",
        default: "any",
        // any  = box mana pun mengakhiri step (paling umum)
        // blue / green = tunggu warna itu saja
        // both = tunggu kedua box terlihat bersamaan
      },
      {
        key: "min_runtime_sec",
        label: "Min Runtime Before Box-Stop (s)",
        type: "number",
        default: 1.5,
        // Deteksi box diabaikan sampai kapal sudah bergerak sekian detik. Tanpa ini,
        // kalau box kebetulan sudah terlihat saat step dimulai, step selesai dalam
        // satu frame dan sapuannya tidak pernah terjadi.
      },
      {
        key: "box_confirm_sec",
        label: "Box Confirm Duration (s)",
        type: "number",
        default: 0.4,
        // Box harus terlihat TERUS-MENERUS selama ini sebelum step diakhiri.
        // Sedikit lebih lama dari versi gerbang: syarat "satu box" lebih mudah
        // terpenuhi daripada "dua warna bola sekaligus", jadi lebih rentan
        // dipicu satu frame false-positive.
      },
      {
        key: "ignore_area_px2",
        label: "Ignore Below Area (px²)",
        type: "number",
        default: 4000,
        // Box dengan area bounding box di bawah nilai ini TIDAK dihitung. Satuannya
        // mengacu resolusi referensi 1920x1080 dan diskalakan otomatis ke resolusi
        // kamera yang sedang dipakai.
      },
    ],
  },
  // ── Sequential Multi-Pair Buoy ─────────────────────────────────────────
  // Tidak ada field konfigurasi jumlah pasangan — engine berjalan otomatis
  // sampai tidak ada lagi pasangan buoy (merah+hijau) yang terdeteksi di frame.
  // Pasangan diurutkan otomatis: yang paling dekat kamera = Pasangan 1.
  // Engine: SEARCHING → LOCKED → TRANSITIONING → CLEARED, lalu lanjut pasangan berikutnya.
  {
    type: "SEQUENTIAL_BUOY",
    label: "Sequential Buoy (Multi-Pair)",
    icon: "🛟",
    color: "text-teal-400",
    bg: "bg-teal-500/10 border-teal-500/30",
    fields: [
      { key: "throttle", label: "Throttle (0-1)", type: "number", default: 0.4 },
      {
        key: "ignore_area_px2",
        label: "Ignore Below Area (px²)",
        type: "number",
        default: 4000,
        // Pasangan bola dengan area rata-rata bounding box di bawah nilai ini
        // dianggap TIDAK ADA sama sekali (bukan sekadar "belum boleh dikunci") —
        // tidak dikejar maupun dikunci. Ini yang membuat step bisa SELESAI walau
        // ada deteksi bola yang sangat jauh (course lain, noise, dst).
      },
      {
        key: "no_detection_finish_sec",
        label: "Finish After No Detection (s)",
        type: "number",
        default: 15,
        // Kalau BENAR-BENAR tidak ada apa pun terdeteksi (tidak ada kandidat
        // pasangan maupun fallback gate_x) selama durasi ini, step dianggap
        // SELESAI dan lanjut ke step berikutnya — bukan cuma berhenti bergerak.
        // Berlaku sejak awal step, tidak peduli sudah ada pasangan yang cleared
        // atau belum.
      },
      {
        key: "single_ball_clearance_px",
        label: "Single-Ball Clearance (px)",
        type: "number",
        default: 384,
        // Saat cuma 1 warna bola terdeteksi (pairing gagal total), kapal menjaga
        // jarak bola ini ke tengah frame minimal sebesar ini — bukan mengejar
        // posisinya. Di bawah jarak ini koreksi menjauh mulai diterapkan.
      },
      {
        key: "single_ball_max_steer",
        label: "Single-Ball Max Steer (0-1)",
        type: "number",
        default: 0.4,
        // Steer maksimum koreksi jaga-jarak bola tunggal, dicapai saat bola
        // tepat di tengah frame (paling bahaya).
      },
      {
        key: "locked_timeout_area_growth_min_ratio",
        label: "Locked-Timeout Auto-Count Growth (x)",
        type: "number",
        default: 1.5,
        // Kalau kapal LOCKED >8 detik pada pasangan yang sama (kedua bola tidak
        // pernah hilang dari frame), dan area pasangan sudah membesar sebesar
        // rasio ini sejak lock pertama, dihitung sebagai 1 pasangan cleared
        // otomatis — bukti kapal sudah mendekat/lewat, bukan cuma diam.
      },
      {
        key: "transitioning_lean_timeout_sec",
        label: "Max Lean Duration Before Auto-Clear (s)",
        type: "number",
        default: 20,
        // Berapa lama kapal boleh menahan manuver condong PAKSA (kiri/kanan
        // konstan, ke arah bola yang hilang) sebelum jaring pengaman terakhir
        // memaksa pasangan dianggap cleared — untuk kasus bola tersisa TERUS
        // terdeteksi tanpa henti (mis. false-positive statis). TIDAK memotong
        // manuver yang masih valid: kapal tetap menahan arah lean sampai bola
        // tersisa BENAR hilang atau durasi ini terlampaui, mana pun lebih dulu.
      },
      {
        key: "gate_balance_deadband",
        label: "Gate Balance Deadband (0-1)",
        type: "number",
        default: 0.25,
        // ANTI-TABRAK: toleransi ketidakseimbangan celah kiri-vs-kanan haluan
        // sebelum kapal dikoreksi menjauh dari bola yang lebih dekat. TURUNKAN
        // kalau kapal masih menyenggol bola, NAIKKAN kalau kapal jadi goyah.
      },
      {
        key: "gate_max_avoid_steer",
        label: "Gate Max Avoid Steer (0-1)",
        type: "number",
        default: 0.5,
        // Kekuatan MAKSIMUM koreksi anti-tabrak di atas, dicapai saat salah satu
        // bola tepat di garis haluan kapal.
      },
      {
        key: "transition_use_next_pair",
        label: "Handoff To Next Gate (1=on, 0=off)",
        type: "number",
        default: 1,
        // Saat satu bola gerbang ini hilang (jumlah bola jadi ganjil), kapal
        // langsung membidik gerbang BERIKUTNYA yang masih utuh, bukan condong
        // buta ke arah bola yang hilang. Bola sisa gerbang lama dibuang dari
        // pairing supaya tidak bikin "gerbang hantu", dan kapal tetap dijaga
        // jaraknya dari bola sisa itu. Set 0 untuk kembali ke perilaku lama.
      },
      {
        key: "transition_lean_magnitude",
        label: "Transition Lean Strength (0-1)",
        type: "number",
        default: 0.4,
        // Kekuatan condong PAKSA saat satu bola hilang.
      },
    ],
  },
  // ── Buoy Chase (Simple Tracking) ────────────────────────────────────────
  // Versi permukaan-konfigurasi SEDERHANA dari SEQUENTIAL_BUOY di atas — TANPA
  // target pass_count. Selesai OTOMATIS begitu buoy habis dari frame, sama
  // seperti SEQUENTIAL_BUOY, dan gerak penutupnya (durasi + miring kiri/kanan)
  // bisa diatur di sini.
  // Delegasi penuh ke engine SEQUENTIAL_BUOY (safeguard pairing, TRANSITIONING,
  // safety timeout — semua sudah teruji lapangan lewat step itu).
  {
    type: "BUOY_CHASE",
    label: "Buoy Chase (Simple Tracking)",
    icon: "🎣",
    color: "text-lime-400",
    bg: "bg-lime-500/10 border-lime-500/30",
    fields: [
      { key: "throttle", label: "Throttle (0-1)", type: "number", default: 0.4 },
      {
        key: "ignore_area_px2",
        label: "Ignore Below Area (px²)",
        type: "number",
        default: 4000,
        // Bola/pasangan dengan area bounding box di bawah nilai ini dianggap
        // "terlalu jauh" dan diabaikan total — tidak dikejar maupun dikunci.
        // Naikkan kalau kapal masih tertarik ke bola jauh, turunkan kalau
        // bola dekat yang sah malah ikut terbuang.
      },
      // ── Perilaku saat buoy HABIS dari pandangan ────────────────────────
      // Menggantikan field "Max Lean Duration Before Auto-Clear (s)" yang dulu
      // ada di sini. Field itu SEBENARNYA mengatur hal lain — batas waktu
      // condong paksa saat SATU bola dari gerbang yang sudah dikunci hilang —
      // bukan perilaku "buoy sudah habis" seperti yang diduga. Ia tetap ada di
      // panel Sequential Buoy; di sini dihapus dan jatuh ke default engine (20s).
      {
        key: "blind_search_timeout_sec",
        label: "Move Duration When No Buoy (s)",
        type: "number",
        default: 5,
        // Lama kapal tetap BERGERAK saat tidak ada buoy sama sekali di frame.
        // Dulu HARDCODED 5 detik dan tidak bisa diubah dari panel. Lewat durasi
        // ini kapal BERHENTI (throttle 0) — jangan dibuat besar tanpa alasan,
        // batas ini yang mencegah kapal melaju buta sampai keluar arena.
      },
      {
        key: "blind_lean_percent",
        label: "Move Lean % (-100 left .. +100 right)",
        type: "number",
        default: 0,
        // Arah & besar miring selama bergerak buta itu: negatif = KIRI,
        // positif = KANAN, 0 = maju lurus (perilaku lama). Kecepatannya ikut
        // field Throttle di atas. Berguna untuk menyusul lintasan yang membelok
        // setelah buoy terakhir lepas dari pandangan.
      },
      {
        key: "no_detection_finish_sec",
        label: "Finish Step After No Buoy (s)",
        type: "number",
        default: 15,
        // Setelah sekian lama tanpa buoy, step dianggap SELESAI dan misi lanjut.
        // WAJIB lebih besar dari "Move Duration" di atas — kalau tidak, step
        // keburu selesai sebelum durasi geraknya habis dan miringnya tidak
        // pernah terlihat penuh.
      },
      {
        key: "gate_balance_deadband",
        label: "Gate Balance Deadband (0-1)",
        type: "number",
        default: 0.25,
        // ANTI-TABRAK: toleransi ketidakseimbangan celah kiri-vs-kanan haluan
        // sebelum kapal dikoreksi menjauh dari bola yang lebih dekat. Steer
        // midpoint saja tidak cukup karena pakai piksel MUTLAK — meleset 60px
        // di gerbang sempit jauh lebih bahaya daripada di gerbang lebar, tapi
        // midpoint memperlakukan keduanya sama. TURUNKAN kalau kapal masih
        // menyenggol bola, NAIKKAN kalau kapal jadi goyah/terlalu mengoreksi.
      },
      {
        key: "gate_max_avoid_steer",
        label: "Gate Max Avoid Steer (0-1)",
        type: "number",
        default: 0.5,
        // Kekuatan MAKSIMUM koreksi anti-tabrak di atas, dicapai saat salah satu
        // bola tepat di garis haluan kapal (paling bahaya).
      },
      {
        key: "transition_use_next_pair",
        label: "Handoff To Next Gate (1=on, 0=off)",
        type: "number",
        default: 1,
        // Saat satu bola gerbang ini hilang (jumlah bola jadi ganjil), kapal
        // langsung membidik gerbang BERIKUTNYA yang masih utuh, bukan condong
        // buta ke arah bola yang hilang. Bola sisa gerbang lama dibuang dari
        // pairing supaya tidak bikin "gerbang hantu", dan kapal tetap dijaga
        // jaraknya dari bola sisa itu. Set 0 untuk kembali ke perilaku lama.
      },
      {
        key: "transition_lean_magnitude",
        label: "Transition Lean Strength (0-1)",
        type: "number",
        default: 0.4,
        // Kekuatan condong PAKSA saat satu bola hilang. Naikkan kalau kapal
        // masih menyenggol bola tersisa saat melintas, turunkan kalau kapal
        // terlalu membanting keluar jalur.
      },
    ],
  },
  // ── Misi foto box biru & hijau ─────────────────────────────────────────
  // WAJIB diletakkan SETELAH salah satu step buoy (Tracking Buoy / Sequential
  // Buoy / Buoy Chase). Kapal menolak menjalankannya lebih awal: engine menahan
  // posisi lalu melewati step ini, dan mengirim peringatan ke panel ini.
  //
  // SATU KAMERA. Box biru konsepnya target bawah air dan box hijau target atas
  // air, tapi di arena box biru masih menyembul di permukaan — keduanya dipotret
  // dari kamera permukaan yang sama. Tidak ada kamera underwater di sistem ini.
  {
    type: "PHOTO_BOX",
    label: "Photo Box (Biru & Hijau)",
    icon: "📷",
    color: "text-blue-400",
    bg: "bg-blue-500/10 border-blue-500/30",
    fields: [
      {
        key: "target",
        label: "Target (both / blue / green)",
        type: "text",
        default: "both",
        // Urutan default: biru dulu, karena bagiannya yang terlihat dari permukaan
        // paling kecil sehingga paling butuh kapal mendekat.
      },
      {
        key: "throttle",
        label: "Approach Throttle (0-1)",
        type: "number",
        default: 0.25,
        // Kecepatan meluncur mendekati box setelah lurus di depan haluan.
      },
      {
        key: "search_throttle",
        label: "Search Throttle (0-1)",
        type: "number",
        default: 0.15,
        // Kecepatan saat menyapu mencari box yang belum terlihat.
      },
      {
        key: "search_steer",
        label: "Search Steer (-1 kiri .. +1 kanan)",
        type: "number",
        default: 0.25,
        // Arah sapuan saat mencari. Ubah tandanya kalau box berada di sisi kiri
        // lintasan setelah gerbang terakhir.
      },
      {
        key: "align_threshold_px",
        label: "Align Tolerance (px)",
        type: "number",
        default: 120,
        // Seberapa dekat box harus ke garis tengah frame sebelum kapal mulai maju.
        // Nilai default diskalakan otomatis ke resolusi kamera aktual oleh engine.
      },
      {
        key: "min_area_px2_blue",
        label: "Close Enough — Blue Box (px²)",
        type: "number",
        default: 60000,
        // SENGAJA terpisah dari box hijau: box biru sebagian terendam, sehingga
        // bagian yang terlihat kamera permukaan lebih kecil pada jarak yang sama.
        // Satu ambang untuk keduanya membuat kapal menabrak box hijau atau tidak
        // pernah merasa cukup dekat ke box biru.
      },
      {
        key: "min_area_px2_green",
        label: "Close Enough — Green Box (px²)",
        type: "number",
        default: 90000,
      },
      {
        key: "settle_sec",
        label: "Settle Before Shutter (s)",
        type: "number",
        default: 1.2,
        // Lama kapal harus DIAM sebelum memotret. Foto dari kapal yang masih
        // meluncur akan buram dan miring saat dinilai juri.
      },
      {
        key: "search_timeout_sec",
        label: "Give Up Searching After (s)",
        type: "number",
        default: 20,
        // Batas mencari SATU box sebelum menyerah dan lanjut ke target berikutnya.
        // Menyerah lebih baik daripada menahan seluruh misi demi satu foto.
      },
    ],
  },
  // ── Lewat celah antar box + foto keduanya ──────────────────────────────
  // Box TIDAK berdampingan seperti bola gerbang — letaknya BERSELANG di sepanjang
  // lintasan (biru lebih dulu di kanan, hijau menyusul di kiri). Karena itu titik
  // tengah dua objek tidak bisa dipakai: yang satu jauh lebih dekat dari yang lain,
  // dan keduanya sering tidak terlihat bersamaan.
  //
  // Yang dipakai: KONVENSI SISI — biru menandai tepi KANAN, hijau menandai tepi
  // KIRI, jadi SATU box yang terlihat sudah cukup untuk tahu di sebelah mana
  // celahnya. Kapal berhenti dan memusatkan tiap box sebelum menjepret, lalu
  // kembali menyusuri celah menuju box berikutnya.
  // BOX_APPROACH — cari satu box, dekati, lalu menghindar. Tanpa foto.
  //
  // Bedanya dengan BOX_CHANNEL: step itu mengurus DUA box sekaligus, menyusuri
  // celah di antaranya, dan memotret keduanya. Step ini sengaja dibuat sesederhana
  // mungkin — satu box, tiga fase, dan SEMUA angkanya terbuka untuk di-tuning —
  // supaya perilaku yang benar bisa dicari dulu di danau tanpa variabel lain ikut
  // berubah. Untuk box kedua, pasang step ini sekali lagi dengan target hijau.
  //
  // Urutan setelah buoy ditentukan oleh POSISI step di pipeline: taruh step ini
  // sesudah step buoy. Tidak ada gerbang tersembunyi di dalamnya.
  {
    type: "BOX_APPROACH",
    label: "Box: Cari → Dekati → Hindar",
    icon: "🎯",
    color: "text-indigo-400",
    bg: "bg-indigo-500/10 border-indigo-500/30",
    fields: [
      {
        key: "target",
        label: "Cari Box Warna",
        type: "text",
        default: "blue",
        // "blue"/"biru" atau "green"/"hijau". Default biru sesuai urutan lintasan.
      },

      // ─── Fase 1: SCAN — mencari box ────────────────────────────────────
      {
        key: "scan_throttle",
        label: "1. CARI — Throttle",
        type: "number",
        default: 0.25,
        // Laju kapal selama box belum terlihat.
      },
      {
        key: "scan_steer",
        label: "1. CARI — Belok (− kiri / + kanan)",
        type: "number",
        default: 0.25,
        // Arah SEKALIGUS sensitivitas sapuan, dalam satu angka bertanda:
        //   -0.4 = menyapu ke kiri, agak tajam
        //    0   = maju lurus, tanpa menyapu
        //   +0.25 = menyapu ke kanan, landai
        // Digabung jadi satu field, bukan dipisah arah + kekuatan, supaya tidak
        // mungkin ada kombinasi yang saling bertentangan.
      },
      {
        key: "scan_timeout_sec",
        label: "1. CARI — Menyerah Setelah (s)",
        type: "number",
        default: 25,
        // Box tidak ketemu selama ini → step DISELESAIKAN, bukan digantung.
        // Kapal yang menyapu tanpa batas akan keluar arena.
      },

      // ─── Fase 2: APPROACH — mendekati box ──────────────────────────────
      {
        key: "approach_throttle",
        label: "2. DEKATI — Throttle",
        type: "number",
        default: 0.25,
        // Laju saat box sudah terlihat dan kapal mendekat.
      },
      {
        key: "approach_steer_gain",
        label: "2. DEKATI — Sensitivitas Pemusatan",
        type: "number",
        default: 1.0,
        // Naikkan kalau kapal lambat meluruskan ke box.
        // Turunkan kalau kapal bergoyang kiri-kanan (osilasi) saat mendekat.
      },
      {
        key: "max_steer",
        label: "2. DEKATI — Batas Kemudi",
        type: "number",
        default: 0.5,
        // Sensitivitas yang kebesaran tidak boleh berubah jadi bantingan penuh.
      },
      {
        key: "min_detect_area_px2",
        label: "2. DEKATI — Abaikan Bbox < (px²)",
        type: "number",
        default: 3000,
        // Bbox lebih kecil dari ini bukan dianggap box. Wajib ada: satu pantulan
        // air yang lolos YOLO cukup membuat kapal mengunci sasaran palsu.
      },
      {
        key: "lost_grace_sec",
        label: "2. DEKATI — Toleransi Box Hilang (s)",
        type: "number",
        default: 1.0,
        // Box berkedip hilang → kemudi terakhir dipertahankan selama ini dulu,
        // baru kembali mencari. Tanpa ini kapal meluruskan haluan tiap kedipan.
      },

      // ─── Pemicu menghindar ─────────────────────────────────────────────
      {
        key: "center_tolerance_px",
        label: "3. PICU — Toleransi Tengah (px)",
        type: "number",
        default: 120,
        // "Sudah di titik tengah" = simpangan box dari tengah frame <= ini.
      },
      {
        key: "target_area_px2",
        label: "3. PICU — Ukuran Target (px²)",
        type: "number",
        default: 45000,
        // "Sudah dekat" = luas bbox >= ini. INI yang menentukan pada JARAK berapa
        // kapal mulai menghindar. Ditulis dalam satuan 1920x1080 dan diskalakan
        // otomatis ke resolusi kamera — jangan dikonversi sendiri.
      },
      {
        key: "force_evade_area_ratio",
        label: "3. PICU — Pengaman Tabrakan (x target)",
        type: "number",
        default: 1.8,
        // Dua syarat di atas harus terpenuhi BERSAMAAN. Kalau box tak pernah
        // benar-benar terpusat, syarat itu tak pernah terpenuhi sementara kapal
        // terus mendekat — dan satu-satunya yang menghentikannya adalah box itu
        // sendiri. Begitu luas bbox melewati target x angka ini, kapal menghindar
        // walau belum terpusat. Isi 0 untuk mematikan (tidak disarankan).
      },

      // ─── Fase 3: EVADE — manuver menghindar ────────────────────────────
      {
        key: "evade_direction",
        label: "4. HINDAR — Arah (kiri/kanan/auto)",
        type: "text",
        default: "left",
        // "left"/"kiri", "right"/"kanan", atau "auto".
        // Default KIRI karena box biru menandai tepi KANAN lintasan — menghindar
        // ke kiri membawa kapal ke tengah celah, bukan keluar alur.
        // "auto" menurunkannya dari warna box: biru → kiri, hijau → kanan.
      },
      {
        key: "evade_throttle",
        label: "4. HINDAR — Throttle",
        type: "number",
        default: 0.3,
        // Laju selama manuver menghindar. Kalau kemudi kapal servo, jangan terlalu
        // kecil — tanpa aliran air kemudinya tidak menggigit dan bantingannya lemah.
      },
      {
        key: "evade_steer",
        label: "4. HINDAR — Kuat Bantingan",
        type: "number",
        default: 0.5,
        // Hanya kekuatannya (0..1). Arahnya diambil dari field arah di atas.
      },
      {
        key: "evade_sec",
        label: "4. HINDAR — Durasi (s)",
        type: "number",
        default: 2.0,
        // Lama membanting sebelum step dianggap selesai.
      },

      // ─── Pengaman ──────────────────────────────────────────────────────
      {
        key: "max_duration_sec",
        label: "Batas Keras Seluruh Step (s)",
        type: "number",
        default: 90,
        // Berlaku di fase mana pun. Ada karena batas CARI di atas me-reset setiap
        // kali kapal sempat melihat box: deteksi berkedip bisa membuat CARI dan
        // DEKATI bergantian tanpa pernah kedaluwarsa. Isi 0 untuk mematikan.
      },
    ],
  },

  {
    type: "BOX_CHANNEL",
    label: "Box Channel (Lewat Tengah + Foto)",
    icon: "📦",
    color: "text-cyan-400",
    bg: "bg-cyan-500/10 border-cyan-500/30",
    fields: [
      {
        key: "mode",
        label: "Mode (stop / moving)",
        type: "text",
        default: "stop",
        // stop   = berhenti, putar sampai box di tengah, diam, baru jepret.
        //          Foto paling tajam. Lintasan terputus sebentar tiap box.
        // moving = tidak pernah berhenti: pusatkan sambil melaju, jepret, lalu
        //          MEMBANTING MENJAUH dari box. Lebih cepat dan lintasan utuh,
        //          tapi foto berisiko sedikit blur.
        // Dua-duanya di step yang SAMA supaya bisa dibandingkan di danau cukup
        // dengan mengganti satu nilai ini.
      },
      {
        key: "throttle",
        label: "Transit Throttle (0-1)",
        type: "number",
        default: 0.3,
        // Laju saat menyusuri celah. Di mode moving, laju ini juga dipertahankan
        // saat membidik dan menghindar — kapal tidak boleh kehilangan momentum
        // tepat sebelum manuver menghindar.
      },
      {
        key: "evade_sec",
        label: "Lama Menghindar (s) — mode moving",
        type: "number",
        default: 1.5,
        // Setelah menjepret sambil jalan, kapal sedang mengarah TEPAT ke box.
        // Ini lama membanting menjauh sebelum kembali menyusuri celah.
        // Tidak dipakai di mode stop — di sana kapal berhenti jauh dari box.
      },
      {
        key: "evade_steer",
        label: "Kuat Menghindar (0-1) — mode moving",
        type: "number",
        default: 0.45,
        // Arahnya TIDAK perlu diisi: diturunkan dari warna box (biru menandai tepi
        // kanan → menghindar ke kiri, hijau sebaliknya). Ini hanya kekuatannya.
      },
      {
        key: "aim_throttle",
        label: "Aim Throttle (0-1)",
        type: "number",
        default: 0.08,
        // Laju saat MEMBIDIK. SENGAJA tidak nol: kemudi kapal ini memakai servo
        // GroundSteering yang butuh aliran air untuk menggigit — tanpa laju sama
        // sekali kapal tidak berputar dan fase membidik hanya kehabisan waktu.
        // Turunkan ke 0 kalau thruster diferensial ternyata sanggup memutar di tempat.
      },
      {
        key: "box_width_m",
        label: "Lebar Box Sebenarnya (m) — UKUR INI",
        type: "number",
        default: 0.5,
        // Kunci dari cara offset yang benar. Kalau diisi, jarak lewat dihitung
        // ulang tiap frame dari lebar box di layar, sehingga tetap sekian METER
        // berapa pun jarak kapal ke box. Isi 0 untuk kembali memakai offset
        // piksel tetap di bawah (tidak disarankan — lihat catatannya).
      },
      {
        key: "channel_offset_m",
        label: "Jarak Lewat dari Box (m)",
        type: "number",
        default: 1.0,
        // Setengah lebar celah. Celah 2 m → 1.0. Perkecil kalau kapal terlalu
        // melebar keluar alur, perbesar kalau lewat terlalu mepet ke box.
        // Hanya dipakai kalau "Lebar Box Sebenarnya" juga diisi.
      },
      {
        key: "channel_offset_px",
        label: "Channel Offset — mode piksel (cadangan)",
        type: "number",
        default: 420,
        // HANYA dipakai kalau "Lebar Box Sebenarnya" dikosongkan/0.
        //
        // Offset piksel tetap cuma benar pada SATU jarak: 280px (di 1280) berarti
        // 0,71 m saat box 2 m di depan, tapi 2,13 m saat 6 m. Di celah 2 m, kapal
        // akan membidik jauh di luar alur selama masih jauh. Pakai mode meter di
        // atas kalau lebar box sudah diukur.
      },
      {
        key: "align_threshold_px",
        label: "Align Tolerance (px)",
        type: "number",
        default: 140,
        // Seberapa dekat box harus ke tengah frame sebelum shutter ditekan.
      },
      {
        key: "min_area_px2_blue",
        label: "Stop & Foto — Box Biru (px²)",
        type: "number",
        default: 45000,
        // Ambang "cukup dekat untuk dibidik". Dipisah per warna karena box biru
        // sebagian terendam, jadi bagian yang terlihat kamera permukaan lebih
        // kecil pada jarak yang sama.
      },
      {
        key: "min_area_px2_green",
        label: "Stop & Foto — Box Hijau (px²)",
        type: "number",
        default: 70000,
      },
      {
        key: "settle_sec",
        label: "Settle Sebelum Shutter (s)",
        type: "number",
        default: 1.0,
        // Lama kapal harus DIAM sebelum memotret, supaya foto tidak buram/miring.
      },
      {
        key: "aim_timeout_sec",
        label: "Batas Membidik (s)",
        type: "number",
        default: 6,
        // Lewat ini, box difoto dengan framing seadanya. Menjepret apa adanya jauh
        // lebih baik daripada kapal merayap mendekat tanpa henti mengejar
        // pemusatan sempurna — itu yang berujung menyenggol box.
      },
      {
        key: "blind_stop_sec",
        label: "Berhenti Setelah Tanpa Box (s)",
        type: "number",
        default: 8,
        // Tidak ada box terlihat sama sekali: kapal maju lurus selama ini lalu
        // BERHENTI. Batas inilah yang mencegah kapal melaju buta keluar arena.
      },
      {
        key: "no_detection_finish_sec",
        label: "Selesaikan Step Setelah (s)",
        type: "number",
        default: 20,
        // WAJIB lebih besar dari "Berhenti Setelah Tanpa Box" di atas.
      },
    ],
  },
  {
    type: "FINISH",
    label: "Mission Complete",
    icon: "🏁",
    color: "text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-500/30",
    fields: [],
  },
];

export const getStepTypeDef = (type) => STEP_TYPES.find((s) => s.type === type) || null;

// ─── Mission Store ────────────────────────────────────────────────────────────
export const useMissionStore = defineStore("mission", () => {
  // Mission pipeline steps (user-defined)
  const steps = ref([]);

  // Live mission status from backend
  const missionStatus = ref("IDLE");    // IDLE, RUNNING, PAUSED, FINISHED, ABORTED
  const currentStepIdx = ref(0);
  const currentStep = ref({});
  const totalSteps = ref(0);
  const elapsedSec = ref(0);
  const buoyPassCount = ref(0);

  // Sequential Buoy live state (sync dari MISSION_STATUS payload)
  const seqPairsCleared = ref(0);  // berapa pasang buoy yang sudah berhasil dilewati
  const seqCurrentPair  = ref(1);  // pasangan yang sedang diincar (1-indexed)

  // Legacy (for timeline component compatibility)
  const currentStep_legacy = ref(1);
  const missionElapsedSeconds = ref(0);
  const waypoints = ref([]);

  // ─── Waypoint Management ──────────────────────────────────────────────────
  function addWaypoint(lat, lng) {
    waypoints.value.push({ lat, lng });
  }

  function removeWaypoint(index) {
    waypoints.value.splice(index, 1);
  }

  function clearWaypoints() {
    waypoints.value = [];
  }

  // Konversi waypoints ke GOTO_GPS steps dan sisipkan ke pipeline misi.
  // Jika sudah ada step dengan tipe GOTO_GPS, mereka digantikan;
  // jika tidak ada, waypoints disisipkan sebelum step FINISH (atau di akhir).
  function loadWaypointsAsMission() {
    if (!waypoints.value.length) return;
    const gotoSteps = waypoints.value.map((wp, i) => ({
      id: Date.now() + i,
      type: 'GOTO_GPS',
      name: `Waypoint ${(i + 1).toString().padStart(2, '0')}`,
      lat: parseFloat(wp.lat.toFixed(7)),
      lon: parseFloat(wp.lng.toFixed(7)),
    }));
    // Hapus step GOTO_GPS yang sudah ada, sisipkan yang baru sebelum FINISH
    const nonGoto = steps.value.filter(s => s.type !== 'GOTO_GPS');
    const finishIdx = nonGoto.findIndex(s => s.type === 'FINISH');
    if (finishIdx !== -1) {
      nonGoto.splice(finishIdx, 0, ...gotoSteps);
    } else {
      nonGoto.push(...gotoSteps);
    }
    steps.value = nonGoto;
    console.log(`[MissionStore] Loaded ${gotoSteps.length} waypoints as GOTO_GPS steps.`);
  }

  // Timer for UI elapsed counter
  let _timerInterval = null;

  // Formatted time
  const formattedTime = computed(() => {
    const t = elapsedSec.value;
    const m = Math.floor(t / 60).toString().padStart(2, "0");
    const s = (t % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  });

  const stepElapsedSec = ref(0);

  // Dynamic Progress Calculations
  const progressPct = computed(() => {
    if (missionStatus.value === "FINISHED") return 100;
    const total = totalSteps.value || steps.value.length;
    if (!total || missionStatus.value === "IDLE") return 0;

    let baseRatio = currentStepIdx.value / total;

    if (missionStatus.value === "RUNNING" || missionStatus.value === "PAUSED") {
      const step = currentStep.value?.type ? currentStep.value : steps.value[currentStepIdx.value];
      let subRatio = 0;

      if (step) {
        if (step.type === "TRACKING_BUOY" && step.pass_count > 0) {
          subRatio = Math.min(buoyPassCount.value / step.pass_count, 1.0);
        } else if (step.duration_sec && step.duration_sec > 0) {
          subRatio = Math.min(stepElapsedSec.value / step.duration_sec, 1.0);
        }
      }

      baseRatio += subRatio / total;
    }

    return Math.min(100, Math.round(baseRatio * 100));
  });

  const activeStepLabel = computed(() => {
    if (missionStatus.value === "FINISHED") return "Mission Complete";
    if (missionStatus.value === "IDLE") {
      const total = steps.value.length;
      if (!total) return "No Steps Configured";
      return `Ready (${total} Steps)`;
    }
    if (missionStatus.value === "ABORTED") return "Mission Aborted";

    const step = currentStep.value?.type ? currentStep.value : steps.value[currentStepIdx.value];
    if (!step) return `Step ${currentStepIdx.value + 1}`;

    const stepNum = (currentStepIdx.value + 1).toString().padStart(2, '0');
    const totalNum = (totalSteps.value || steps.value.length).toString().padStart(2, '0');

    if (step.type === "START") {
      const remaining = Math.max(0, Math.ceil((step.duration_sec || 2) - stepElapsedSec.value));
      return `[${stepNum}/${totalNum}] Warmup (${remaining}s)`;
    }

    if (step.type === "TRACKING_BUOY") {
      const passTarget = step.pass_count || 1;
      const passed = buoyPassCount.value || 0;
      return `[${stepNum}/${totalNum}] Buoy Gate ${passed}/${passTarget}`;
    }

    if (step.type === "SEQUENTIAL_BUOY") {
      const pairDone = seqPairsCleared.value || 0;
      return `[${stepNum}/${totalNum}] Sequential Buoy — Pair ${seqCurrentPair.value} (${pairDone} cleared)`;
    }

    if (step.type === "BUOY_CHASE") {
      // BUOY_CHASE delegasi ke engine SEQUENTIAL_BUOY, jadi seqPairsCleared/
      // seqGateLockState ikut terisi meski tidak ada konsep target pass_count di sini.
      const found = seqPairsCleared.value || 0;
      return `[${stepNum}/${totalNum}] Buoy Chase (${found} passed)`;
    }

    if (step.duration_sec) {
      const remaining = Math.max(0, Math.ceil(step.duration_sec - stepElapsedSec.value));
      return `[${stepNum}/${totalNum}] ${step.name || step.type} (${remaining}s)`;
    }

    return `[${stepNum}/${totalNum}] ${step.name || step.type}`;
  });


  // ─── Step Builder Actions ─────────────────────────────────────────────────
  function addStep(type) {
    const def = getStepTypeDef(type);
    if (!def) return;
    const defaults = {};
    def.fields.forEach((f) => (defaults[f.key] = f.default));
    steps.value.push({
      id: Date.now(),
      type,
      name: def.label,
      ...defaults,
    });
  }

  function removeStep(index) {
    steps.value.splice(index, 1);
  }

  function moveStep(fromIdx, toIdx) {
    if (toIdx < 0 || toIdx >= steps.value.length) return;
    const arr = [...steps.value];
    const [item] = arr.splice(fromIdx, 1);
    arr.splice(toIdx, 0, item);
    steps.value = arr;
  }

  function updateStep(index, key, value) {
    if (steps.value[index]) {
      steps.value[index][key] = value;
    }
  }

  function clearSteps() {
    steps.value = [];
  }

  // ─── WebSocket Mission Commands ───────────────────────────────────────────

  /**
   * Arsipkan foto run SEBELUMNYA sebelum run baru dimulai.
   *
   * Tanpa ini, slot Underwater/Surface di dashboard masih memampang foto percobaan
   * yang lalu, dan tidak ada cara membedakan mana hasil run yang sedang dinilai —
   * foto lama bahkan terlihat seperti "sudah dapat" padahal run ini belum memotret
   * apa pun.
   *
   * Di server foto lama DIPINDAH ke sub-folder, bukan dihapus, dan salinan aslinya
   * tetap ada di Mini PC. Jadi tidak ada yang hilang; hanya berhenti ditampilkan.
   *
   * Kegagalannya SENGAJA tidak memblokir start misi: dashboard yang menampilkan foto
   * basi jauh lebih ringan akibatnya daripada misi yang gagal dimulai karena satu
   * permintaan housekeeping tidak terjawab.
   */
  async function _arsipkanFotoRunSebelumnya() {
    try {
      const res = await fetch(apiUrl("/api/v1/captures/archive"), {
        method: "POST",
        headers: authHeaders(),
      });
      if (!res.ok) {
        console.warn(`[MissionStore] Pengarsipan foto gagal (HTTP ${res.status}) — misi tetap dimulai.`);
      }
    } catch (e) {
      console.warn("[MissionStore] Pengarsipan foto gagal — misi tetap dimulai:", e);
    }
  }

  async function loadAndStartMission() {
    if (!steps.value.length) return;
    const wsStore = useWebsocketStore();
    const stepsPayload = steps.value.map((s, i) => ({ ...s, id: i + 1 }));

    await _arsipkanFotoRunSebelumnya();
    wsStore.sendCommand({ action: "arm" });
    wsStore.sendCommand({ action: "set_mode", mode: "GUIDED" });
    wsStore.sendCommand({ action: "start_mission", steps: stepsPayload });
  }

  async function startMission() {
    if (!steps.value.length) return;
    const wsStore = useWebsocketStore();
    const stepsPayload = steps.value.map((s, i) => ({ ...s, id: i + 1 }));

    await _arsipkanFotoRunSebelumnya();
    wsStore.sendCommand({ action: "arm" });
    wsStore.sendCommand({ action: "set_mode", mode: "GUIDED" });
    wsStore.sendCommand({ action: "start_mission", steps: stepsPayload });
    missionStatus.value = "RUNNING";
    _startLocalTimer();
  }



  function pauseMission() {
    const wsStore = useWebsocketStore();
    wsStore.sendCommand({ action: "pause_mission" });
    missionStatus.value = "PAUSED";
    _stopLocalTimer();
  }

  function resumeMission() {
    const wsStore = useWebsocketStore();
    wsStore.sendCommand({ action: "resume_mission" });
    missionStatus.value = "RUNNING";
    _startLocalTimer();
  }

  function abortMission() {
    const wsStore = useWebsocketStore();
    wsStore.sendCommand({ action: "abort_mission" });
    missionStatus.value = "ABORTED";
    _stopLocalTimer();
  }

  function resetMission() {
    const wsStore = useWebsocketStore();
    wsStore.sendCommand({ action: "reset_mission" });
    missionStatus.value = "IDLE";
    currentStepIdx.value = 0;
    elapsedSec.value = 0;
    buoyPassCount.value = 0;
    _stopLocalTimer();
  }

  // ─── Live Status Update from WS ──────────────────────────────────────────
  function updateMissionStatus(payload) {
    missionStatus.value = payload.status || "IDLE";
    currentStepIdx.value = payload.current_step_idx ?? 0;
    currentStep.value = payload.current_step ?? {};
    totalSteps.value = payload.total_steps ?? 0;
    stepElapsedSec.value = payload.step_elapsed_sec ?? 0;
    buoyPassCount.value = payload.buoy_pass_count ?? 0;
    currentStep_legacy.value = (payload.current_step_idx ?? 0) + 1;

    // Sequential Buoy live state — dikirim oleh MissionEngine.get_status_dict()
    seqPairsCleared.value = payload.seq_pairs_cleared ?? 0;
    seqCurrentPair.value  = payload.seq_current_pair  ?? 1;

    if (missionStatus.value === "RUNNING" && !_timerInterval) {
      _startLocalTimer();
    } else if (missionStatus.value !== "RUNNING") {
      _stopLocalTimer();
    }
  }

  // ─── Presets & Database Persistence ───────────────────────────────────────
  const dbPresets = ref([]);

  const presets = computed(() => dbPresets.value);

  async function fetchPresets() {
    try {
      const res = await fetch(apiUrl("/api/v1/mission-presets"));
      if (res.ok) {
        const json = await res.json();
        if (json.status === "success" && Array.isArray(json.data)) {
          dbPresets.value = json.data.map((item) => {
            let parsedSteps = [];
            try {
              parsedSteps = typeof item.steps === "string" ? JSON.parse(item.steps) : item.steps;
            } catch (e) {
              parsedSteps = [];
            }
            return {
              id: `db_${item.id}`,
              dbId: item.id,
              name: item.name,
              steps: parsedSteps,
              isDb: true,
            };
          });
        }
      }
    } catch (e) {
      console.warn("[MissionStore] Failed to fetch presets from database:", e);
    }
  }

  async function saveCurrentAsPreset(presetName) {
    if (!steps.value.length) return false;
    const name = presetName || `Mission ${new Date().toLocaleString('id-ID')}`;
    try {
      const res = await fetch(apiUrl("/api/v1/mission-presets"), {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          name: name,
          steps: JSON.stringify(steps.value),
        }),
      });
      if (res.ok) {
        await fetchPresets();
        return true;
      }
    } catch (e) {
      console.error("[MissionStore] Failed to save preset to database:", e);
    }
    return false;
  }

  async function deletePreset(dbId) {
    try {
      const res = await fetch(apiUrl(`/api/v1/mission-presets/${dbId}`), {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (res.ok) {
        await fetchPresets();
        return true;
      }
    } catch (e) {
      console.error("[MissionStore] Failed to delete preset:", e);
    }
    return false;
  }

  function loadPreset(preset) {
    steps.value = preset.steps.map((s) => ({ ...s, id: Date.now() + Math.random() }));
  }

  // Fetch presets from DB on init; steps mulai kosong
  fetchPresets();


  // ─── Internal ─────────────────────────────────────────────────────────────
  function _startLocalTimer() {
    if (_timerInterval) return;
    _timerInterval = setInterval(() => {
      elapsedSec.value++;
    }, 1000);
  }

  function _stopLocalTimer() {
    if (_timerInterval) {
      clearInterval(_timerInterval);
      _timerInterval = null;
    }
  }

  // Legacy compat
  const missionSteps = computed(() =>
    steps.value.map((s, i) => ({ id: i + 1, name: s.name || s.type }))
  );

  return {
    // State
    steps, missionStatus, currentStepIdx, currentStep, totalSteps,
    elapsedSec, buoyPassCount, formattedTime, progressPct, activeStepLabel, waypoints, presets, dbPresets,
    // Sequential Buoy live state
    seqPairsCleared, seqCurrentPair,
    // Legacy
    missionSteps, currentStep_legacy,
    // Step builder
    addStep, removeStep, moveStep, updateStep, clearSteps,
    // Mission control
    startMission, pauseMission, resumeMission, abortMission, resetMission, loadAndStartMission,
    // Status updater
    updateMissionStatus,
    // Presets & Database
    loadPreset, fetchPresets, saveCurrentAsPreset, deletePreset,
    // Waypoints
    addWaypoint, removeWaypoint, clearWaypoints, loadWaypointsAsMission, stepElapsedSec
  };
});
