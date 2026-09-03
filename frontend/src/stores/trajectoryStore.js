import { defineStore } from "pinia";
import { computed, ref } from "vue";

/**
 * Perekam lintasan (trajectory) kapal — real-time, berjalan di LATAR BELAKANG.
 *
 * KENAPA HARUS DI STORE, BUKAN DI KOMPONEN PETA (bug nyata pada versi sebelumnya):
 *     Jejak dulu ditumpuk di `trailCoords` milik GridMap.vue. Variabel itu hidup
 *     per-instance komponen, jadi:
 *       - berpindah dari Mapping ke Mission Control lalu kembali = SELURUH jejak
 *         hilang, karena komponennya di-unmount dan array-nya lahir kosong lagi;
 *       - selama peta tidak terbuka, TIDAK ADA satu titik pun yang direkam —
 *         padahal operator paling sering menatap halaman lain saat kapal berjalan;
 *       - Mapping dan Juri masing-masing punya salinan sendiri, jadi juri melihat
 *         lintasan yang berbeda dari operator.
 *
 *     Store Pinia hidup selama aplikasi hidup dan tidak terikat komponen mana pun.
 *     Perekaman disuntik dari SATU tempat telemetri masuk (websocketStore), jadi
 *     titik tetap bertambah walau tidak ada peta yang terpasang di layar.
 *
 * AUTO MAUPUN MANUAL: perekam ini tidak pernah melihat status misi untuk MEMUTUSKAN
 * merekam atau tidak — telemetri kapal mengalir tiap 100 ms di thread tersendiri,
 * lepas dari mission engine. Status misi hanya dipakai untuk MEWARNAI titik
 * (otonom vs kemudi manual), tidak pernah untuk menghentikan perekaman.
 *
 * REAKTIVITAS: array titiknya sengaja TIDAK dikembalikan dari store. Pinia
 * me-reactive() apa pun yang dikembalikan setup store, dan itu berarti membuat
 * proxy untuk puluhan ribu objek yang berubah 10x per detik — jank yang tidak
 * perlu. Penggambar membaca lewat ambilTitik() dan cukup mengawasi `versi`.
 */

// ── Gerbang mutu data ────────────────────────────────────────────────────────
/** Fix minimum yang boleh direkam. 2 = 2D, 3 = 3D. */
const FIX_MINIMUM = 2;
/**
 * Kecepatan maksimum yang masuk akal untuk kapal ini (m/s). Titik yang menyiratkan
 * kecepatan di atas ini dalam jeda yang PENDEK adalah glitch GPS, bukan gerakan —
 * 20 m/s = 72 km/h, jauh di atas kemampuan wahana.
 */
const KECEPATAN_MAKS_MS = 20;

// ── Penjarangan & segmentasi ────────────────────────────────────────────────
/**
 * Titik baru direkam hanya kalau sudah bergeser sejauh ini. Tanpa ambang ini,
 * kapal yang DIAM tetap menghasilkan 10 titik per detik berisi derau GPS: buffer
 * penuh oleh getaran di tempat, dan polyline-nya jadi gumpalan.
 */
const JARAK_MINIMUM_M = 0.5;
/**
 * Jeda telemetri selama ini dianggap PUTUS: titik berikutnya memulai segmen baru.
 * Tanpa ini, kapal yang koneksinya putus lalu tersambung lagi 200 m kemudian akan
 * digambar sebagai garis lurus menembus daratan — lintasan yang tidak pernah ada.
 */
const JEDA_SEGMEN_MS = 3000;

// ── Batas memori ────────────────────────────────────────────────────────────
/** ~10 km lintasan pada penjarangan 0,5 m. */
const MAKS_TITIK = 20000;
/**
 * Saat penuh, titik lama dibuang SEKALIGUS sebanyak ini, bukan satu per satu.
 * Array.shift() memindahkan seluruh isi array tiap panggilan — pada 20.000 elemen
 * dan 10 Hz itu jutaan pemindahan per detik. Membuang per blok membuat biayanya
 * teramortisasi mendekati nol.
 */
const BUANG_SEKALIGUS = 2000;

// ── Ketahanan terhadap refresh ──────────────────────────────────────────────
const KUNCI_SESI = "asv.trajectory.v1";
const SIMPAN_TIAP_MS = 5000;
const MAKS_TITIK_DISIMPAN = 6000;

/** Status misi dianggap basi setelah ini — lihat catatan di setStatusMisi(). */
const MISI_BASI_MS = 3000;

const RADIUS_BUMI_M = 6371000;

/** Jarak dua koordinat (meter), haversine. */
function jarakM(lat1, lng1, lat2, lng2) {
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLng = (lng2 - lng1) * rad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * RADIUS_BUMI_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

/** Koordinat yang layak digambar. (0,0) ditolak: itu Null Island, bukan danau. */
function posisiSah(lat, lng) {
  return (
    Number.isFinite(lat) &&
    Number.isFinite(lng) &&
    Math.abs(lat) <= 90 &&
    Math.abs(lng) <= 180 &&
    !(lat === 0 && lng === 0)
  );
}

export const useTrajectoryStore = defineStore("trajectory", () => {
  /**
   * Titik lintasan. SENGAJA di luar sistem reaktif — lihat catatan modul.
   * Bentuk tiap titik: { lat, lng, t, seg, oto }
   */
  let titik = [];

  /** Bertambah tiap ada titik baru. Inilah sinyal yang diawasi penggambar. */
  const versi = ref(0);
  /**
   * Bertambah saat indeks lama TIDAK lagi valid (dibersihkan, dipangkas, atau
   * dipulihkan dari sesi). Penggambar yang menyimpan posisi terakhirnya memakai
   * ini untuk tahu kapan harus menggambar ulang dari nol, bukan menambahkan.
   */
  const epoch = ref(0);

  const merekam = ref(true);
  const mengikutiKapal = ref(true);
  const tampilkan = ref(true);

  // ── Statistik (dihitung inkremental, bukan dengan menyisir seluruh array) ──
  const jumlahTitik = ref(0);
  const jarakTotalM = ref(0);
  const jumlahSegmen = ref(0);
  const waktuMulai = ref(0);
  const waktuTerakhir = ref(0);
  const titikDibuang = ref(0);

  // ── Diagnostik: kenapa sebuah titik TIDAK direkam ─────────────────────────
  const tolakFix = ref(0);
  const tolakLompatan = ref(0);
  const tolakFcPutus = ref(0);

  let segmenSekarang = 0;
  let putusSegmen = true;
  let simpanTerakhirAt = 0;
  /**
   * Kapan telemetri sah TERAKHIR diterima — bukan kapan titik terakhir direkam.
   *
   * Keduanya berbeda jauh saat kapal diam: pembacaan tetap datang 10x per detik
   * tapi tidak ada yang lolos penjarangan. Mengukur jeda dari titik terekam
   * membuat kapal yang menganggur di dermaga tampak seperti telemetri yang putus
   * berulang kali, lengkap dengan segmen palsu tiap beberapa detik.
   */
  let telemetriTerakhirAt = 0;

  // Status misi terakhir yang dilaporkan kapal, dipakai HANYA untuk mewarnai.
  //
  // ref, BUKAN `let` biasa: versi pertama memakai variabel biasa di dalam
  // computed(), dan computed hanya menghitung ulang kalau salah satu dependensi
  // REAKTIF-nya berubah. Variabel biasa tidak pernah memicu apa pun, jadi begitu
  // nilainya sekali menjadi true ia tidak pernah kembali false — seluruh sisa
  // lintasan setelah misi selesai salah warna, termasuk bagian yang dikemudikan
  // manual.
  const misiBerjalan = ref(false);
  const misiUpdateAt = ref(0);

  /**
   * Dihitung langsung, bukan lewat computed: hasilnya bergantung pada Date.now()
   * yang tidak reaktif, jadi computed akan menyimpan jawaban basi sampai ada
   * dependensi lain yang kebetulan berubah.
   */
  function hitungOtonom() {
    return misiBerjalan.value && Date.now() - misiUpdateAt.value < MISI_BASI_MS;
  }

  const sedangOtonom = computed(
    () => (versi.value, waktuTerakhir.value, hitungOtonom())
  );

  const durasiMs = computed(() =>
    waktuMulai.value ? waktuTerakhir.value - waktuMulai.value : 0
  );

  /** Titik terakhir yang direkam, atau null. */
  const titikTerakhir = computed(() => (versi.value, titik.length ? titik[titik.length - 1] : null));

  /**
   * Status misi dari kapal. Dipakai HANYA untuk menandai titik sebagai otonom.
   *
   * Diberi masa kedaluwarsa karena MISSION_STATUS hanya mengalir selama ada misi
   * yang berjalan — kalau kapal berhenti mengirimnya tanpa status penutup,
   * bendera "sedang otonom" akan tertinggal menyala selamanya dan seluruh sisa
   * lintasan salah warna.
   */
  function setStatusMisi(status) {
    misiBerjalan.value = status === "RUNNING";
    misiUpdateAt.value = Date.now();
  }

  /**
   * Rekam satu payload telemetri. Dipanggil dari websocketStore untuk SETIAP
   * pesan TELEMETRY, tanpa peduli halaman mana yang sedang terbuka.
   */
  function rekam(payload) {
    if (!merekam.value || !payload) return;

    const now = Date.now();
    const lat = Number(payload.lat);
    const lng = Number(payload.lng);
    const fix = Number(payload.gps_fix ?? 0);

    // Flight controller putus: koordinat yang datang adalah nilai terakhir yang
    // membeku, bukan posisi sekarang. Merekamnya menghasilkan jejak "kapal diam"
    // yang tampak meyakinkan padahal kapal bisa saja sedang hanyut.
    if (payload.is_connected === false) {
      tolakFcPutus.value++;
      putusSegmen = true;
      return;
    }

    if (!posisiSah(lat, lng) || fix < FIX_MINIMUM) {
      tolakFix.value++;
      // Titik berikutnya memulai segmen baru: selama fix hilang kapal tetap
      // bergerak, dan menyambung lurus ke posisi berikutnya adalah karangan.
      putusSegmen = true;
      return;
    }

    // Jeda dinilai dari aliran telemetri, bukan dari titik terakhir — lihat
    // catatan di telemetriTerakhirAt.
    const jedaMs = telemetriTerakhirAt ? now - telemetriTerakhirAt : 0;
    telemetriTerakhirAt = now;
    if (jedaMs > JEDA_SEGMEN_MS) putusSegmen = true;

    const akhir = titik.length ? titik[titik.length - 1] : null;
    if (akhir && !putusSegmen) {
      const d = jarakM(akhir.lat, akhir.lng, lat, lng);
      const dtMs = Math.max(1, now - akhir.t);

      if (d < JARAK_MINIMUM_M) {
        return; // kapal diam — tidak ada yang perlu ditambahkan
      } else if (d / (dtMs / 1000) > KECEPATAN_MAKS_MS) {
        // Mustahil secara fisik dalam jeda sependek ini → glitch GPS, bukan gerak.
        tolakLompatan.value++;
        return;
      } else {
        jarakTotalM.value += d;
      }
    }

    if (putusSegmen) {
      segmenSekarang += 1;
      jumlahSegmen.value = segmenSekarang;
      putusSegmen = false;
    }

    titik.push({ lat, lng, t: now, seg: segmenSekarang, oto: hitungOtonom() });

    if (titik.length > MAKS_TITIK) {
      titik = titik.slice(BUANG_SEKALIGUS);
      titikDibuang.value += BUANG_SEKALIGUS;
      epoch.value++; // indeks lama tidak valid lagi
    }

    jumlahTitik.value = titik.length;
    if (!waktuMulai.value) waktuMulai.value = now;
    waktuTerakhir.value = now;
    versi.value++;

    if (now - simpanTerakhirAt > SIMPAN_TIAP_MS) {
      simpanTerakhirAt = now;
      simpanKeSesi();
    }
  }

  /** Seluruh titik, array biasa (bukan proxy reaktif). Jangan dimutasi pemanggil. */
  function ambilTitik() {
    return titik;
  }

  /** Titik dari indeks tertentu ke atas — untuk penggambaran inkremental. */
  function ambilSejak(indeks) {
    return indeks >= titik.length ? [] : titik.slice(Math.max(0, indeks));
  }

  /** Titik dikelompokkan per segmen kontinu — bentuk yang dipakai polyline. */
  function ambilSegmen() {
    const keluar = [];
    let segAktif = null;
    for (const p of titik) {
      if (!segAktif || segAktif.seg !== p.seg || segAktif.oto !== p.oto) {
        // Warna berubah di tengah segmen (misi mulai/berhenti) juga memulai
        // potongan baru, TAPI titik terakhir potongan sebelumnya diulang supaya
        // garisnya tidak berlubang di titik peralihan.
        const sambung = segAktif && segAktif.seg === p.seg
          ? [segAktif.titik[segAktif.titik.length - 1]]
          : [];
        segAktif = { seg: p.seg, oto: p.oto, titik: [...sambung, p] };
        keluar.push(segAktif);
      } else {
        segAktif.titik.push(p);
      }
    }
    return keluar;
  }

  function bersihkan() {
    titik = [];
    segmenSekarang = 0;
    putusSegmen = true;
    telemetriTerakhirAt = 0;
    jumlahTitik.value = 0;
    jarakTotalM.value = 0;
    jumlahSegmen.value = 0;
    waktuMulai.value = 0;
    waktuTerakhir.value = 0;
    titikDibuang.value = 0;
    tolakFix.value = 0;
    tolakLompatan.value = 0;
    tolakFcPutus.value = 0;
    versi.value++;
    epoch.value++;
    try {
      sessionStorage.removeItem(KUNCI_SESI);
    } catch {
      // Mode privat / kuota penuh: jejak di memori tetap terhapus, itu yang penting.
    }
  }

  /**
   * Simpan ke sessionStorage supaya refresh yang tidak sengaja tidak menghapus
   * lintasan yang sedang berjalan. sessionStorage, bukan localStorage: jejak ikut
   * hilang saat tab ditutup, sejalan dengan aturan sesi login aplikasi ini.
   *
   * Penulisannya dibatasi tiap 5 detik dan dipicu dari alur perekaman, bukan dari
   * timer terpisah — timer yang lupa dihentikan adalah kebocoran yang baru
   * ketahuan setelah berjam-jam.
   */
  function simpanKeSesi() {
    try {
      const potong = titik.slice(-MAKS_TITIK_DISIMPAN);
      sessionStorage.setItem(
        KUNCI_SESI,
        JSON.stringify({
          v: 1,
          jarakTotalM: jarakTotalM.value,
          titikDibuang: titikDibuang.value,
          titik: potong.map((p) => [
            Number(p.lat.toFixed(7)),
            Number(p.lng.toFixed(7)),
            p.t,
            p.seg,
            p.oto ? 1 : 0,
          ]),
        })
      );
    } catch {
      // Kuota penuh atau mode privat. Perekaman di memori JANGAN ikut berhenti —
      // gagal menyimpan cadangan jauh lebih ringan daripada kehilangan lintasan
      // yang sedang berjalan.
    }
  }

  function pulihkanDariSesi() {
    try {
      const mentah = sessionStorage.getItem(KUNCI_SESI);
      if (!mentah) return;
      const data = JSON.parse(mentah);
      if (!data || data.v !== 1 || !Array.isArray(data.titik)) return;

      titik = data.titik
        .filter((r) => Array.isArray(r) && posisiSah(Number(r[0]), Number(r[1])))
        .map((r) => ({
          lat: Number(r[0]),
          lng: Number(r[1]),
          t: Number(r[2]) || 0,
          seg: Number(r[3]) || 0,
          oto: r[4] === 1,
        }));

      jumlahTitik.value = titik.length;
      jarakTotalM.value = Number(data.jarakTotalM) || 0;
      titikDibuang.value = Number(data.titikDibuang) || 0;
      if (titik.length) {
        segmenSekarang = titik[titik.length - 1].seg;
        jumlahSegmen.value = segmenSekarang;
        waktuMulai.value = titik[0].t;
        waktuTerakhir.value = titik[titik.length - 1].t;
      }
      // Titik berikutnya SELALU memulai segmen baru: antara simpanan terakhir dan
      // sekarang ada jeda yang panjangnya tidak diketahui.
      putusSegmen = true;
      epoch.value++;
      versi.value++;
    } catch {
      // Data sesi rusak: mulai dari kosong. Lebih baik kehilangan jejak lama
      // daripada menggambar lintasan yang isinya tidak bisa dipercaya.
    }
  }

  /** Paksa simpan sekarang juga, tanpa menunggu jendela 5 detik. */
  function simpanSekarang() {
    simpanTerakhirAt = Date.now();
    simpanKeSesi();
  }

  pulihkanDariSesi();

  // Penyimpanan berkala hemat, tapi menyisakan lubang: refresh yang tidak
  // sengaja bisa membuang sampai 5 detik terakhir — dan di kecepatan lomba itu
  // beberapa meter lintasan yang hilang. Kedua peristiwa ini menutupnya.
  // 'pagehide' dipilih ketimbang 'beforeunload' karena ikut terpicu saat tab
  // dibuang di perangkat mobile, tempat 'beforeunload' sering tidak jalan.
  if (typeof window !== "undefined") {
    window.addEventListener("pagehide", simpanSekarang);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") simpanSekarang();
    });
    // Sengaja tidak pernah dilepas: store ini hidup selama aplikasi hidup dan
    // hanya ada satu, jadi tidak ada langganan yang menumpuk.
  }

  return {
    versi, epoch,
    merekam, mengikutiKapal, tampilkan,
    jumlahTitik, jarakTotalM, jumlahSegmen, durasiMs, titikDibuang,
    tolakFix, tolakLompatan, tolakFcPutus,
    sedangOtonom, titikTerakhir,
    rekam, setStatusMisi, bersihkan, simpanSekarang,
    ambilTitik, ambilSejak, ambilSegmen,
  };
});
