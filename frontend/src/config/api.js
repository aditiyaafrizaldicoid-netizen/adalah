/**
 * Satu-satunya tempat frontend membaca alamat backend.
 *
 * Nilainya datang dari frontend/.env (VITE_API_URL). Sebelum ini alamat backend
 * tertulis hardcoded di belasan berkas, jadi pindah base station atau ganti IP
 * berarti menyisir satu per satu — dan yang terlewat baru ketahuan saat lomba.
 *
 * Tidak ada fallback ke localhost. Kalau .env belum diisi, lebih baik gagal
 * dengan pesan yang menyebut sebabnya daripada diam-diam menembak mesin yang
 * salah dan terlihat seperti backend mati.
 */

// Garis miring di ekor ("http://host:3000/") akan menghasilkan "//api/v1/..."
// saat digabung. Dirapikan sekali di sini, bukan di tiap pemanggil.
const RAW_BASE = import.meta.env.VITE_API_URL;

export const API_BASE = RAW_BASE ? RAW_BASE.replace(/\/+$/, "") : "";

if (!API_BASE) {
  console.error(
    "[config/api] VITE_API_URL belum diset. Salin frontend/.env.example ke " +
      "frontend/.env, isi alamat backend, lalu jalankan ulang dev server — " +
      "Vite hanya membaca .env saat start, bukan saat hot reload."
  );
}

/** URL absolut ke endpoint REST, mis. apiUrl("/api/v1/arenas"). */
export function apiUrl(path) {
  return `${API_BASE}${path}`;
}

/**
 * Kunci localStorage tempat access token disimpan.
 *
 * Ada di sini, bukan di authStore, karena tiga pemakai membacanya dan tidak semuanya
 * boleh bergantung pada authStore: websocketStore dipanggil BALIK oleh authStore
 * (impor statis akan melingkar), dan authHeaders() di bawah dipakai store lain yang
 * cuma butuh tokennya, bukan seluruh siklus hidup sesi.
 */
export const TOKEN_KEY = "asv_access_token";

/**
 * Header Authorization untuk permintaan yang MENGUBAH data.
 *
 * Backend mewajibkan JWT pada seluruh POST/PUT/DELETE; GET tetap terbuka karena
 * panel Juri dan Mini PC kapal membacanya tanpa bisa login. Mengembalikan objek
 * kosong kalau belum login, sehingga aman dipakai lewat spread di mana pun.
 */
export function authHeaders() {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Alamat WebSocket diturunkan dari API_BASE, bukan variabel .env tersendiri:
 * dua alamat yang harus diisi terpisah cepat atau lambat akan berbeda isi.
 * http:// menjadi ws://, https:// menjadi wss://.
 */
export const WS_URL = API_BASE
  ? `${API_BASE.replace(/^http/, "ws")}/api/v1/ws/client`
  : "";

/**
 * URL WebSocket lengkap dengan token autentikasi.
 *
 * Token dititipkan di query string, bukan header: handshake WebSocket di browser
 * tidak bisa membawa header Authorization sama sekali. Backend memakainya untuk
 * memutuskan apakah koneksi ini boleh MENGIRIM PERINTAH — tanpa token koneksinya
 * tetap diterima dan tetap menerima telemetri, hanya perintahnya yang ditolak.
 * Itulah yang membuat panel Juri bisa dibuka tanpa login.
 */
export function wsUrl(token) {
  if (!WS_URL) return "";
  return token ? `${WS_URL}?token=${encodeURIComponent(token)}` : WS_URL;
}

/** Stream MJPEG kamera kapal. */
export const VIDEO_STREAM_URL = API_BASE ? `${API_BASE}/api/v1/video/stream` : "";
