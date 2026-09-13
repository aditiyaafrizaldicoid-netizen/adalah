/**
 * Geometri bumi untuk keperluan peta.
 *
 * KENAPA ADA: batas geofence berukuran METER, sementara Mapbox GL tidak punya
 * satu pun bentuk yang satuannya meter — `circle-radius` di GL satuannya PIKSEL,
 * jadi batas 60 m akan tetap sebesar itu di layar walau peta di-zoom, dan tampak
 * menutupi seluruh danau saat zoom-out. Itu bukan sekadar jelek: operator membaca
 * batas itu untuk memutuskan kapal masih aman atau tidak.
 *
 * Maka batasnya dibuat sebagai poligon sungguhan dalam koordinat bumi, yang ikut
 * mengecil dan membesar bersama peta.
 */

const RADIUS_BUMI_M = 6371000.0; // sama persis dengan haversine_m di kapal (control/geodesy.py)

/** FeatureCollection kosong — dipakai sebagai isi awal source sebelum ada data. */
export function koleksiKosong() {
  return { type: "FeatureCollection", features: [] };
}

// ── Kotak geofence ──────────────────────────────────────────────────────────
// ⚠ CERMINAN PERSIS dari kotak_batas() di kapal (control/geodesy.py).
//   Kalau salah satunya diubah, yang lain WAJIB ikut. Peta yang menggambar
//   kotak berbeda dari yang ditegakkan kapal adalah peta yang berbohong
//   tentang satu-satunya hal yang perlu dipercaya operator.

/**
 * Batas kotak dalam DERAJAT: { latMin, latMaks, lonMin, lonMaks }.
 *
 * @param {number} lebarM  bentangan TIMUR-BARAT, penuh (bukan setengah)
 * @param {number} tinggiM bentangan UTARA-SELATAN, penuh
 */
export function kotakBatas(lat, lng, lebarM, tinggiM) {
  const dLat = ((tinggiM / 2) / RADIUS_BUMI_M) * (180 / Math.PI);

  const cosLat = Math.cos((lat * Math.PI) / 180);
  // Lihat catatan kutub di kotak_batas() kapal: pembagian nol menghasilkan
  // batas tak hingga, yang berarti SETIAP posisi dianggap di dalam — geofence
  // yang mati tanpa memberi tahu siapa pun.
  const dLon = Math.abs(cosLat) < 1e-12
    ? 180
    : ((lebarM / 2) / (RADIUS_BUMI_M * cosLat)) * (180 / Math.PI);

  return {
    latMin: lat - dLat, latMaks: lat + dLat,
    lonMin: lng - dLon, lonMaks: lng + dLon,
  };
}

/** Kotak geofence sebagai Feature Polygon GeoJSON. */
export function kotakGeoJSON(lat, lng, lebarM, tinggiM) {
  const b = kotakBatas(lat, lng, lebarM, tinggiM);
  const cincin = [
    [b.lonMin, b.latMin],
    [b.lonMaks, b.latMin],
    [b.lonMaks, b.latMaks],
    [b.lonMin, b.latMaks],
    // Cincin poligon GeoJSON WAJIB tertutup: titik terakhir sama persis dengan
    // yang pertama. Tanpa ini Mapbox menolak geometrinya dan kotaknya hilang
    // tanpa satu pun pesan error di layar.
    [b.lonMin, b.latMin],
  ];
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [cincin] },
  };
}

/** Jarak permukaan bumi antara dua koordinat, METER. Cerminan haversine_m kapal. */
export function haversineM(lat1, lng1, lat2, lng2) {
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLng = (lng2 - lng1) * rad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * RADIUS_BUMI_M * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/**
 * Seberapa dalam sebuah posisi berada di dalam kotak, dalam METER.
 * Positif = di dalam, negatif = di luar. Cerminan margin_kotak_m() di kapal.
 *
 * Dipakai peta untuk menilai posisi kapal terhadap batas TANPA menunggu kapal
 * melapor — sehingga batas yang baru digambar tapi belum disimpan pun sudah
 * bisa diperiksa sebelum misi berangkat.
 */
export function marginKotakM(lat, lng, lebarM, tinggiM, titikLat, titikLng) {
  const dNs = haversineM(lat, lng, titikLat, lng);
  const dEw = haversineM(lat, lng, lat, titikLng);

  const keluarNs = Math.max(0, dNs - tinggiM / 2);
  const keluarEw = Math.max(0, dEw - lebarM / 2);
  if (keluarNs > 0 || keluarEw > 0) return -Math.hypot(keluarNs, keluarEw);

  return Math.min(tinggiM / 2 - dNs, lebarM / 2 - dEw);
}
