/**
 * Penyimpanan sesi login — satu-satunya tempat aplikasi ini menyimpan dan membaca
 * token.
 *
 * KENAPA sessionStorage, BUKAN localStorage:
 *   localStorage bertahan sampai dihapus manual. Operator yang menutup browser di
 *   akhir sesi lomba akan tetap ditemukan dalam keadaan login saat browsernya
 *   dibuka lagi berhari-hari kemudian — di laptop yang sama yang dipakai bergantian
 *   banyak orang di meja base station. Tidak ada satu pun yang memutus sesi itu:
 *   router hanya memeriksa APAKAH token ada, tidak pernah apakah masih berlaku.
 *
 *   sessionStorage dibuang browser begitu tab/jendelanya ditutup, sehingga membuka
 *   aplikasi lagi selalu meminta kata sandi. Konsekuensi yang perlu diketahui:
 *   penyimpanannya per-TAB. Membuka aplikasi di tab kedua berarti login lagi di tab
 *   itu — disengaja, dan itulah harga dari sesi yang benar-benar berakhir.
 *
 * Kedaluwarsa token juga dihormati sekarang (lihat isTokenExpired). Sebelumnya
 * access token yang sudah lewat 1 jam tetap dianggap sah oleh router, dan operator
 * baru sadar saat perintah ke kapal mulai ditolak tanpa sebab yang terlihat.
 */

const store = window.sessionStorage;

export const TOKEN_KEY = "asv_access_token";
export const REFRESH_KEY = "asv_refresh_token";
export const USER_KEY = "asv_user";

// Anggap token sudah mati sedikit LEBIH AWAL dari waktu sebenarnya. Jam browser dan
// jam server tidak pernah persis sama, dan token yang lolos pemeriksaan lalu ditolak
// server satu detik kemudian jauh lebih membingungkan daripada refresh yang kepagian.
const CLOCK_SKEW_MS = 30_000;

/**
 * Buang sisa sesi lama dari localStorage.
 *
 * Versi sebelumnya menyimpan di sana. Tanpa pembersihan ini, token milik sesi lama
 * tetap tertinggal di disk pada browser yang sudah pernah dipakai — tidak lagi
 * terbaca aplikasi, tapi tetap kredensial yang tergeletak. Dipanggil sekali saat
 * modul ini dimuat.
 */
function purgeLegacyStorage() {
  try {
    [TOKEN_KEY, REFRESH_KEY, USER_KEY].forEach((k) => window.localStorage.removeItem(k));
  } catch {
    // Mode privasi ketat bisa memblokir localStorage sepenuhnya — tidak apa-apa,
    // tidak ada yang perlu dibersihkan kalau memang tidak bisa ditulis.
  }
}
purgeLegacyStorage();

export function getToken() {
  return store.getItem(TOKEN_KEY) || "";
}

export function getRefreshToken() {
  return store.getItem(REFRESH_KEY) || "";
}

export function getUser() {
  try {
    const raw = store.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveSession({ accessToken, refreshToken, user }) {
  if (accessToken) store.setItem(TOKEN_KEY, accessToken);
  else store.removeItem(TOKEN_KEY);

  if (refreshToken) store.setItem(REFRESH_KEY, refreshToken);
  else store.removeItem(REFRESH_KEY);

  if (user) store.setItem(USER_KEY, JSON.stringify(user));
  else store.removeItem(USER_KEY);
}

/**
 * Header Authorization untuk permintaan yang MENGUBAH data.
 *
 * Backend mewajibkan JWT pada seluruh POST/PUT/DELETE; GET tetap terbuka karena
 * panel Juri dan Mini PC kapal membacanya tanpa bisa login. Mengembalikan objek
 * kosong kalau belum login, sehingga aman dipakai lewat spread di mana pun.
 */
export function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Isi payload JWT, atau null kalau tokennya tidak bisa dibaca. */
function decodePayload(token) {
  try {
    const part = String(token).split(".")[1];
    if (!part) return null;
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const pad = b64.length % 4 ? "=".repeat(4 - (b64.length % 4)) : "";
    return JSON.parse(atob(b64 + pad));
  } catch {
    return null;
  }
}

/**
 * Waktu kedaluwarsa token dalam milidetik epoch, atau null kalau tidak diketahui.
 *
 * Ini pembacaan klaim di sisi klien SAJA, dipakai untuk memutuskan kapan menyegarkan
 * sesi — BUKAN pemeriksaan keamanan. Tanda tangan token tidak diverifikasi di sini
 * dan memang tidak bisa; yang menolak token palsu tetap backend.
 */
export function tokenExpiryMs(token) {
  const payload = decodePayload(token);
  if (!payload || typeof payload.exp !== "number") return null;
  return payload.exp * 1000;
}

/** True kalau token kosong, tidak terbaca, atau sudah (hampir) kedaluwarsa. */
export function isTokenExpired(token) {
  if (!token) return true;
  const exp = tokenExpiryMs(token);
  // Token yang klaim exp-nya tidak terbaca diperlakukan sebagai MASIH berlaku:
  // membuangnya akan memaksa logout untuk format token yang sah tapi tak terduga.
  // Kalau ternyata benar-benar mati, backend yang akan menolaknya dengan 401.
  if (exp === null) return false;
  return Date.now() >= exp - CLOCK_SKEW_MS;
}
