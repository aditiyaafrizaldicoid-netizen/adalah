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
// `import.meta.env?.` — bukan langsung: di luar Vite (mis. berkas uji yang
// dijalankan node) `import.meta.env` tidak ada sama sekali, dan mengaksesnya
// langsung melempar TypeError saat modul dimuat. Rantai opsional membuat modul
// ini tetap bisa diimpor, lalu jatuh ke peringatan yang sudah ada di bawah.
const RAW_BASE = import.meta.env?.VITE_API_URL;

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
