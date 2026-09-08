import { watch } from "vue";
import { useTrajectoryStore } from "@/stores/trajectoryStore";
import { koleksiKosong } from "@/utils/geo";

/**
 * Menggambar lintasan kapal di peta Mapbox GL, mengikuti trajectoryStore.
 *
 * Dipisah dari GridMap.vue supaya peta mana pun (Mapping, Juri, dashboard) bisa
 * menampilkan lintasan yang SAMA PERSIS — datanya satu, penggambarnya seragam.
 * Sebelumnya tiap peta menumpuk jejaknya sendiri, jadi halaman juri dan halaman
 * operator bisa menunjukkan lintasan yang berbeda untuk kapal yang sama.
 *
 * DUA WARNA, SATU LINTASAN: potongan yang direkam saat misi otonom berjalan
 * digambar beda warna dari yang dikemudikan manual. Ini bukan hiasan — itulah
 * bukti terlihat bahwa perekaman memang tidak terputus saat kendali berpindah.
 */

const WARNA_OTONOM = "#22d3ee"; // cyan
const WARNA_MANUAL = "#f59e0b"; // amber
const TEBAL_GARIS = 3;

/**
 * Satu potongan ditutup setiap sekian titik.
 *
 * Alasannya berubah setelah pindah dari Leaflet, tapi tetap berlaku. Dulu:
 * Leaflet menggambar ulang seluruh path tiap kali addLatLng dipanggil. Sekarang:
 * Mapbox GL tidak menerima "tambah satu titik" sama sekali — satu-satunya cara
 * mengubah data adalah setData(), yang MENGIRIM ULANG SELURUH isi source ke GPU.
 * Pada 20.000 titik, satu titik baru berarti menyerialkan 20.000 koordinat, dan
 * itu terjadi tiap kali kapal bergerak setengah meter.
 *
 * Maka datanya dipecah ke DUA source: potongan yang sudah ditutup (jarang
 * berubah — hanya saat potongan baru dimulai) dan potongan yang sedang diisi
 * (berubah terus, tapi isinya tidak pernah lebih dari batas ini).
 */
const MAKS_TITIK_PER_GARIS = 500;

const SRC_SELESAI = "lintasan-selesai";
const SRC_AKTIF = "lintasan-aktif";

/** Empat layer: dua source × dua ragam kendali. */
const LAYERS = [
  { id: "lintasan-selesai-oto", source: SRC_SELESAI, oto: true },
  { id: "lintasan-selesai-manual", source: SRC_SELESAI, oto: false },
  { id: "lintasan-aktif-oto", source: SRC_AKTIF, oto: true },
  { id: "lintasan-aktif-manual", source: SRC_AKTIF, oto: false },
];

export function useTrajectoryLayer() {
  const traj = useTrajectoryStore();

  let map = null;
  let terpasang = false;

  /** Potongan yang sudah ditutup. Bentuk: { oto, seg, koordinat: [[lng,lat],…] } */
  let potongan = [];
  /** Potongan yang sedang diisi. */
  let potonganAktif = null;

  let kunciSekarang = null; // `${seg}:${oto}` — potongan berganti saat ini berubah
  let indeksTerlukis = 0;
  let epochTerlukis = -1;

  // DUA sakelar terpisah yang digabung dengan DAN, bukan satu flag yang saling
  // ditimpa: panel lintasan mematikan tampilan di SEMUA peta sekaligus, sementara
  // daftar layer tiap peta ("trail") hanya mengatur peta itu sendiri. Satu flag
  // untuk keduanya membuat mematikan salah satunya diam-diam menyalakan yang lain.
  let tampilGlobal = traj.tampilkan;
  let tampilPeta = true;

  /** Potongan → FeatureCollection. Sifat `oto` dibawa supaya layer bisa memfilter. */
  function koleksiDari(daftar) {
    return {
      type: "FeatureCollection",
      features: daftar
        // LineString berisi satu titik tidak menggambar apa pun dan hanya
        // membebani serialisasi — potongan yang baru lahir selalu begitu.
        .filter((p) => p.koordinat.length >= 2)
        .map((p) => ({
          type: "Feature",
          properties: { oto: p.oto },
          geometry: { type: "LineString", coordinates: p.koordinat },
        })),
    };
  }

  function tulisSource(id, koleksi) {
    if (!map) return;
    const src = map.getSource(id);
    if (src) src.setData(koleksi);
  }

  function tulisSelesai() {
    tulisSource(SRC_SELESAI, koleksiDari(potongan));
  }

  function tulisAktif() {
    tulisSource(SRC_AKTIF, koleksiDari(potonganAktif ? [potonganAktif] : []));
  }

  /**
   * Gambar ulang dari nol. Dipakai saat indeks lama tidak lagi valid.
   *
   * KEDUA source ditulis tanpa syarat, dan itu bukan kelebihan kehati-hatian:
   * saat lintasan baru saja DIBERSIHKAN, tidak ada satu titik pun untuk disusun,
   * jadi tidak ada penulisan yang terpicu dengan sendirinya. Tanpa penulisan
   * paksa di sini, potongan terakhir tetap membekas di peta setelah operator
   * menekan "bersihkan" — lintasan yang sudah dihapus tapi masih terlihat, yang
   * artinya peta menampilkan bukti gerak yang tidak lagi ada datanya.
   */
  function gambarUlang() {
    if (!terpasang) return;
    potongan = [];
    potonganAktif = null;
    kunciSekarang = null;
    indeksTerlukis = 0;
    susun(traj.ambilTitik());
    epochTerlukis = traj.epoch;
    tulisSelesai();
    tulisAktif();
  }

  /**
   * Susun titik ke dalam potongan. TIDAK menulis ke peta — penulisannya urusan
   * pemanggil, karena gambar ulang dan penambahan biasa punya aturan berbeda.
   * Mengembalikan true kalau ada potongan yang ditutup.
   */
  function susun(titikBaru) {
    let selesaiBerubah = false;

    for (const p of titikBaru) {
      const kunci = `${p.seg}:${p.oto ? 1 : 0}`;
      const penuh =
        potonganAktif && potonganAktif.koordinat.length >= MAKS_TITIK_PER_GARIS;

      if (kunci !== kunciSekarang || penuh) {
        // Potongan baru. Kalau masih segmen yang sama (cuma ganti warna atau
        // sudah kepanjangan), titik terakhir potongan sebelumnya diulang sebagai
        // titik pertama — tanpa itu garisnya berlubang tepat di tiap peralihan.
        const segmenSama =
          potonganAktif && kunciSekarang && kunciSekarang.split(":")[0] === String(p.seg);
        const jembatan = segmenSama
          ? [potonganAktif.koordinat[potonganAktif.koordinat.length - 1]]
          : [];

        if (potonganAktif) {
          potongan.push(potonganAktif);
          selesaiBerubah = true;
        }
        potonganAktif = {
          oto: !!p.oto,
          seg: p.seg,
          // [lng, lat] — urutan GeoJSON. Leaflet dulu memakai kebalikannya.
          koordinat: [...jembatan, [p.lng, p.lat]],
        };
        kunciSekarang = kunci;
      } else {
        potonganAktif.koordinat.push([p.lng, p.lat]);
      }
    }

    indeksTerlukis = traj.ambilTitik().length;
    return selesaiBerubah;
  }

  /** Tambahkan titik-titik baru ke ujung lintasan, tanpa menggambar ulang. */
  function tambahkan(titikBaru) {
    if (!titikBaru.length) return;
    // Source "selesai" hanya ditulis saat benar-benar bertambah. Inilah yang
    // membuat kapal berjalan hanya membayar serialisasi potongan aktif.
    if (susun(titikBaru)) tulisSelesai();
    tulisAktif();
  }

  function segarkan() {
    if (!terpasang) return;
    if (traj.epoch !== epochTerlukis) {
      // Dibersihkan, dipangkas, atau dipulihkan dari sesi — indeks lama menunjuk
      // titik yang berbeda sekarang, jadi menambahkan saja akan salah sambung.
      gambarUlang();
      return;
    }
    const baru = traj.ambilSejak(indeksTerlukis);
    if (baru.length) tambahkan(baru);
  }

  function terapkanTampil() {
    if (!terpasang) return;
    const tampak = tampilGlobal && tampilPeta ? "visible" : "none";
    for (const l of LAYERS) {
      if (map.getLayer(l.id)) map.setLayoutProperty(l.id, "visibility", tampak);
    }
  }

  /** Sakelar layer milik peta ini saja (dari prop visibleLayers). */
  function setTampil(nilai) {
    tampilPeta = !!nilai;
    terapkanTampil();
  }

  /**
   * Pasang ke peta. WAJIB dipanggil setelah gaya peta selesai dimuat —
   * addSource/addLayer sebelum itu melempar "Style is not done loading".
   */
  function pasang(mapInstance) {
    map = mapInstance;
    if (!map) return;

    for (const id of [SRC_SELESAI, SRC_AKTIF]) {
      if (!map.getSource(id)) {
        map.addSource(id, { type: "geojson", data: koleksiKosong() });
      }
    }

    for (const l of LAYERS) {
      if (map.getLayer(l.id)) continue;
      map.addLayer({
        id: l.id,
        type: "line",
        source: l.source,
        // Warna dan pola garis dipisah PER LAYER, bukan satu layer dengan
        // ekspresi berbasis data: line-dasharray tidak bisa digerakkan oleh
        // properti fitur, jadi garis putus-putus manual mustahil dalam satu layer.
        filter: ["==", ["get", "oto"], l.oto],
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": l.oto ? WARNA_OTONOM : WARNA_MANUAL,
          "line-width": TEBAL_GARIS,
          "line-opacity": 0.9,
          // Satuan dasharray di Mapbox adalah KELIPATAN TEBAL GARIS, bukan
          // piksel: [2,2] pada tebal 3 menghasilkan 6 px putus / 6 px kosong,
          // sama seperti dashArray "6, 6" milik Leaflet dulu.
          //
          // Manual digambar putus-putus supaya tetap terbedakan oleh operator
          // yang kesulitan membedakan warna, dan pada rekaman layar yang pucat.
          ...(l.oto ? {} : { "line-dasharray": [2, 2] }),
        },
      });
    }

    terpasang = true;
    terapkanTampil();
    // Gambar ulang dari nol: peta ini baru lahir, sementara lintasannya sudah
    // berjalan sejak sebelum peta dibuka — itulah inti perekaman di latar belakang.
    gambarUlang();
  }

  function lepas() {
    if (map) {
      // Layer dibuang sebelum source: Mapbox menolak membuang source yang masih
      // dirujuk layer mana pun.
      for (const l of LAYERS) {
        if (map.getLayer(l.id)) map.removeLayer(l.id);
      }
      for (const id of [SRC_SELESAI, SRC_AKTIF]) {
        if (map.getSource(id)) map.removeSource(id);
      }
    }
    map = null;
    terpasang = false;
    potongan = [];
    potonganAktif = null;
    kunciSekarang = null;
    indeksTerlukis = 0;
    epochTerlukis = -1;
  }

  // Satu pengawas untuk versi DAN epoch. Watcher-nya otomatis dihentikan saat
  // komponen pemanggil di-unmount, jadi tidak ada langganan yang tertinggal.
  watch(
    () => [traj.versi, traj.epoch],
    () => segarkan()
  );

  watch(
    () => traj.tampilkan,
    (v) => {
      tampilGlobal = !!v;
      terapkanTampil();
    }
  );

  return { pasang, lepas, setTampil, gambarUlang };
}
