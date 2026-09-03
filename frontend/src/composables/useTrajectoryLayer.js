import { watch } from "vue";
import L from "leaflet";
import { useTrajectoryStore } from "@/stores/trajectoryStore";

/**
 * Menggambar lintasan kapal di peta Leaflet, mengikuti trajectoryStore.
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

/**
 * Satu polyline dipotong setiap sekian titik.
 *
 * Leaflet menggambar ULANG seluruh path setiap kali addLatLng dipanggil. Pada satu
 * polyline berisi 20.000 titik, tiap titik baru berarti menggambar ulang 20.000
 * segmen — peta tersendat justru saat kapal sedang berjalan. Dengan dipotong,
 * penggambaran ulang paling banyak menyentuh sebanyak ini saja.
 */
const MAKS_TITIK_PER_GARIS = 500;

export function useTrajectoryLayer() {
  const traj = useTrajectoryStore();

  let map = null;
  let grup = null;
  let garisSekarang = null;
  let kunciSekarang = null; // `${seg}:${oto}` — potongan berganti saat ini berubah
  let jumlahDiGaris = 0;
  let indeksTerlukis = 0;
  let epochTerlukis = -1;

  // DUA sakelar terpisah yang digabung dengan DAN, bukan satu flag yang saling
  // ditimpa: panel lintasan mematikan tampilan di SEMUA peta sekaligus, sementara
  // daftar layer tiap peta ("trail") hanya mengatur peta itu sendiri. Satu flag
  // untuk keduanya membuat mematikan salah satunya diam-diam menyalakan yang lain.
  let tampilGlobal = traj.tampilkan;
  let tampilPeta = true;

  function gayaGaris(oto) {
    return {
      color: oto ? WARNA_OTONOM : WARNA_MANUAL,
      weight: 3,
      opacity: 0.9,
      lineJoin: "round",
      lineCap: "round",
      // Manual digambar putus-putus supaya tetap terbedakan oleh operator yang
      // kesulitan membedakan warna, dan pada rekaman layar yang pucat.
      dashArray: oto ? null : "6, 6",
    };
  }

  function mulaiGaris(oto, titikAwal) {
    garisSekarang = L.polyline(titikAwal, gayaGaris(oto));
    if (grup) garisSekarang.addTo(grup);
    jumlahDiGaris = titikAwal.length;
  }

  /** Gambar ulang dari nol. Dipakai saat indeks lama tidak lagi valid. */
  function gambarUlang() {
    if (!grup) return;
    grup.clearLayers();
    garisSekarang = null;
    kunciSekarang = null;
    jumlahDiGaris = 0;
    indeksTerlukis = 0;
    tambahkan(traj.ambilTitik());
    epochTerlukis = traj.epoch;
  }

  /** Tambahkan titik-titik baru ke ujung lintasan, tanpa menggambar ulang. */
  function tambahkan(titikBaru) {
    for (const p of titikBaru) {
      const kunci = `${p.seg}:${p.oto ? 1 : 0}`;

      if (kunci !== kunciSekarang || jumlahDiGaris >= MAKS_TITIK_PER_GARIS) {
        // Potongan baru. Kalau masih segmen yang sama (cuma ganti warna atau
        // sudah kepanjangan), titik terakhir potongan sebelumnya diulang sebagai
        // titik pertama — tanpa itu garisnya berlubang tepat di tiap peralihan.
        const segmenSama =
          garisSekarang && kunciSekarang && kunciSekarang.split(":")[0] === String(p.seg);
        const jembatan = segmenSama ? [garisSekarang.getLatLngs().slice(-1)[0]] : [];
        mulaiGaris(p.oto, [...jembatan, [p.lat, p.lng]]);
        kunciSekarang = kunci;
      } else {
        garisSekarang.addLatLng([p.lat, p.lng]);
        jumlahDiGaris++;
      }
    }
    indeksTerlukis = traj.ambilTitik().length;
  }

  function segarkan() {
    if (!grup) return;
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
    if (!map || !grup) return;
    const harusTampil = tampilGlobal && tampilPeta;
    if (harusTampil && !map.hasLayer(grup)) grup.addTo(map);
    else if (!harusTampil && map.hasLayer(grup)) map.removeLayer(grup);
  }

  /** Sakelar layer milik peta ini saja (dari prop visibleLayers). */
  function setTampil(nilai) {
    tampilPeta = !!nilai;
    terapkanTampil();
  }

  function pasang(mapInstance) {
    map = mapInstance;
    grup = L.layerGroup();
    terapkanTampil();
    // Gambar ulang dari nol: peta ini baru lahir, sementara lintasannya sudah
    // berjalan sejak sebelum peta dibuka — itulah inti perekaman di latar belakang.
    gambarUlang();
  }

  function lepas() {
    if (map && grup && map.hasLayer(grup)) map.removeLayer(grup);
    grup = null;
    map = null;
    garisSekarang = null;
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
