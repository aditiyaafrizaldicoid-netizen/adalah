/**
 * Geometri bumi untuk keperluan peta.
 *
 * KENAPA ADA: Leaflet punya L.circle yang radiusnya METER — kita menggambar
 * geofence dengan itu. Mapbox GL tidak punya padanannya: `circle-radius` di GL
 * satuannya PIKSEL, jadi lingkaran yang digambar dengannya akan tetap sebesar
 * itu di layar walau peta di-zoom — dan geofence 60 m akan tampak menutupi
 * seluruh danau saat zoom-out. Itu bukan sekadar jelek: operator membaca batas
 * itu untuk memutuskan kapal masih aman atau tidak.
 *
 * Maka lingkarannya dibuat sebagai poligon sungguhan dalam koordinat bumi, yang
 * ikut mengecil dan membesar bersama peta persis seperti L.circle dulu.
 */

const RADIUS_BUMI_M = 6371008.8; // radius rata-rata IUGG, sama dengan yang dipakai turf

/**
 * Titik tujuan sejauh `jarakM` meter dari (lat, lng) pada arah `bearingDeg`.
 * Rumus great-circle standar di atas bola.
 */
function titikTujuan(lat, lng, jarakM, bearingDeg) {
  const rad = Math.PI / 180;
  const deg = 180 / Math.PI;

  const d = jarakM / RADIUS_BUMI_M; // jarak sudut
  const t = bearingDeg * rad;
  const lat1 = lat * rad;
  const lng1 = lng * rad;

  const sinLat2 =
    Math.sin(lat1) * Math.cos(d) + Math.cos(lat1) * Math.sin(d) * Math.cos(t);
  const lat2 = Math.asin(Math.min(1, Math.max(-1, sinLat2)));
  const lng2 =
    lng1 +
    Math.atan2(
      Math.sin(t) * Math.sin(d) * Math.cos(lat1),
      Math.cos(d) - Math.sin(lat1) * sinLat2
    );

  return [lng2 * deg, lat2 * deg]; // [lng, lat] — urutan GeoJSON, bukan urutan Leaflet
}

/**
 * Lingkaran radius-meter sebagai Feature Polygon GeoJSON.
 *
 * @param {number} lat    pusat
 * @param {number} lng    pusat
 * @param {number} radiusM radius dalam METER
 * @param {number} segmen  jumlah sisi poligon; 128 sudah tak terbedakan dari lingkaran
 */
export function lingkaranGeoJSON(lat, lng, radiusM, segmen = 128) {
  const cincin = [];
  for (let i = 0; i < segmen; i++) {
    cincin.push(titikTujuan(lat, lng, radiusM, (i * 360) / segmen));
  }
  // Cincin poligon GeoJSON WAJIB tertutup: titik terakhir sama persis dengan
  // yang pertama. Tanpa ini Mapbox menolak geometrinya dan lingkaran hilang
  // tanpa pesan error apa pun di layar.
  cincin.push(cincin[0]);

  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [cincin] },
  };
}

/** FeatureCollection kosong — dipakai sebagai isi awal source sebelum ada data. */
export function koleksiKosong() {
  return { type: "FeatureCollection", features: [] };
}
