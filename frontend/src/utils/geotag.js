/**
 * Format geo-tag untuk "Position and Mission Imaging Infos".
 *
 * CERMINAN dari flightcontrolAsv1/camera/geotag.py — dua berkas ini HARUS menghasilkan
 * string yang identik. Kalau salah satu diubah, ubah keduanya: layar base station dan
 * geo-tag yang tercetak di foto misi tidak boleh berbeda format saat dinilai.
 *
 * Field wajib menurut lembar ketentuan:
 *   Day [Sun..Sat] · Date [DD/MM/YYYY] · Time [hh:mm:ss]
 *   Coordinate Format A: [S 3.56734 E 104.67235]
 *   Coordinate Format B: [S 3° 43,5423' E 104° 33,6445']
 *   SOG dalam knot DAN km/h · COG dalam derajat
 *
 * Catatan pemisah desimal: lembar ketentuan tidak konsisten (judul Format A menulis
 * [DD,DDDD] dengan koma, contohnya memakai titik). Yang diikuti di sini adalah
 * CONTOH-nya — sama seperti di sisi kapal. Ubah DECIMAL_SEP_A kalau ternyata harus koma.
 */

// getDay(): Minggu = 0. Ditulis eksplisit, bukan toLocaleDateString, agar tidak
// berubah mengikuti locale browser operator (bisa keluar "Jum" alih-alih "Fri").
const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const DECIMAL_SEP_A = '.';
const DECIMAL_SEP_B = ',';

/** 1 knot = 1.852 km/jam. Store menyimpan SOG dalam KNOT (lihat vesselStore). */
export const KMH_PER_KNOT = 1.852;

const pad2 = (n) => String(n).padStart(2, '0');

export const formatDay = (d) => DAY_NAMES[d.getDay()];

export const formatDate = (d) =>
  `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()}`;

export const formatTime = (d) =>
  `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;

const hemisphere = (value, isLat) =>
  isLat ? (value >= 0 ? 'N' : 'S') : (value >= 0 ? 'E' : 'W');

/** Format A — Degree, Decimal. Contoh: "S 3.56734 E 104.67235" */
export function formatCoordA(lat, lng, decimals = 5) {
  const f = (v) => Math.abs(v).toFixed(decimals).replace('.', DECIMAL_SEP_A);
  return `${hemisphere(lat, true)} ${f(lat)} ${hemisphere(lng, false)} ${f(lng)}`;
}

function degMin(value, decimals = 4) {
  const absolute = Math.abs(value);
  let degrees = Math.floor(absolute);
  const minutes = (absolute - degrees) * 60;
  let minutesStr = minutes.toFixed(decimals);
  // Pembulatan bisa menyentuh 60,0000 — itu bukan koordinat sah, naikkan derajatnya.
  if (parseFloat(minutesStr) >= 60) {
    degrees += 1;
    minutesStr = (0).toFixed(decimals);
  }
  return `${degrees}° ${minutesStr.replace('.', DECIMAL_SEP_B)}'`;
}

/** Format B — Degree, Minute. Contoh: "S 3° 43,5423' E 104° 33,6445'" */
export function formatCoordB(lat, lng) {
  return `${hemisphere(lat, true)} ${degMin(lat)} ${hemisphere(lng, false)} ${degMin(lng)}`;
}
