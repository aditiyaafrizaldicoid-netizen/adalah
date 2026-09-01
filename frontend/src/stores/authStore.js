import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { API_BASE } from "@/config/api";
import {
  getRefreshToken,
  getToken,
  getUser,
  isTokenExpired,
  saveSession,
  tokenExpiryMs,
} from "@/utils/session";

// Seberapa awal sebelum kedaluwarsa access token disegarkan. Cukup longgar agar
// satu kali kegagalan jaringan masih menyisakan waktu untuk mencoba lagi, dan agar
// perintah ke kapal tidak pernah ditolak di tengah lomba hanya karena token habis.
const REFRESH_LEAD_MS = 120_000;

/**
 * Sambung ulang WebSocket setelah hak akses berubah.
 *
 * Backend menetapkan boleh-tidaknya sebuah koneksi mengirim perintah SEKALI saat
 * handshake, dari token di query string. Koneksi yang dibuka App.vue sebelum login
 * karena itu bersifat baca-saja selamanya — tombol ARM dan misi akan diam saja
 * sampai koneksinya dibuka ulang membawa token yang baru.
 *
 * Lazy import: authStore dimuat router guard saat aplikasi mulai, sedangkan
 * websocketStore menarik vesselStore & missionStore. Impor statis di sini membuat
 * rantai itu ikut dievaluasi lebih awal dari yang diperlukan.
 */
function refreshSocketAuth() {
  import("./websocketStore")
    .then(({ useWebsocketStore }) => useWebsocketStore().reconnect())
    .catch((e) => console.warn("[auth] Gagal menyambung ulang WebSocket:", e));
}

export const useAuthStore = defineStore("auth", () => {
  const user = ref(getUser());
  const accessToken = ref(getToken());
  const refreshToken = ref(getRefreshToken());
  const isLoading = ref(false);
  const error = ref("");

  const isAuthenticated = computed(() => !!accessToken.value);
  const isAdmin = computed(() => user.value?.role === "admin");

  function persist() {
    saveSession({
      accessToken: accessToken.value,
      refreshToken: refreshToken.value,
      user: user.value,
    });
  }

  function clearSession() {
    cancelScheduledRefresh();
    user.value = null;
    accessToken.value = "";
    refreshToken.value = "";
    persist();
  }

  // ── Perpanjangan sesi otomatis ────────────────────────────────────────
  // Sesi berakhir saat browser ditutup (sessionStorage), TAPI selama tab masih
  // terbuka ia tidak boleh mati sendiri: access token hanya berumur 1 jam, dan
  // habisnya di tengah lomba berarti tombol KILL SWITCH ikut lumpuh sampai
  // operator sempat login ulang. Jadi token disegarkan diam-diam sebelum habis.
  let refreshTimer = null;

  function cancelScheduledRefresh() {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = null;
  }

  function scheduleRefresh() {
    cancelScheduledRefresh();
    const exp = tokenExpiryMs(accessToken.value);
    if (!exp) return;   // klaim exp tidak terbaca — biarkan backend yang menolak
    // Minimal 5 detik: token yang sudah nyaris mati saat halaman dibuka tetap
    // dijadwalkan, bukan disegarkan berulang-ulang dalam satu putaran event loop.
    const delay = Math.max(5_000, exp - Date.now() - REFRESH_LEAD_MS);
    refreshTimer = setTimeout(() => { refreshSession(); }, delay);
  }

  /**
   * Pastikan ada access token yang masih berlaku, menyegarkannya kalau perlu.
   * Dipakai router guard sebelum mengizinkan masuk ke halaman terproteksi.
   * @returns {Promise<boolean>} false berarti sesi harus dimulai dari login.
   */
  async function ensureFreshSession() {
    if (!accessToken.value) return false;
    if (!isTokenExpired(accessToken.value)) {
      if (!refreshTimer) scheduleRefresh();
      return true;
    }
    // Access token habis. Refresh token berumur jauh lebih panjang (168 jam),
    // jadi biasanya masih bisa ditukar — kecuali memang sudah lewat juga.
    if (!refreshToken.value || isTokenExpired(refreshToken.value)) {
      clearSession();
      return false;
    }
    return await refreshSession();
  }

  // Header Authorization untuk request lain yang butuh token.
  function authHeader() {
    return accessToken.value ? { Authorization: `Bearer ${accessToken.value}` } : {};
  }

  // Backend membungkus semua respons: { statusCode, success, message, data }
  async function login(email, password) {
    isLoading.value = true;
    error.value = "";
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const body = await res.json().catch(() => null);

      if (!res.ok || !body?.success) {
        // Pesan validasi per-field lebih berguna daripada "Bad Request" generik.
        const detail = body?.errors?.[0]?.message;
        throw new Error(detail || body?.message || `Login gagal (HTTP ${res.status})`);
      }

      accessToken.value = body.data.access_token;
      refreshToken.value = body.data.refresh_token;
      user.value = body.data.user;
      persist();
      scheduleRefresh();
      refreshSocketAuth();
      return true;
    } catch (e) {
      // fetch melempar TypeError kalau server tidak bisa dihubungi sama sekali —
      // "Failed to fetch" tidak berarti apa-apa buat operator di lapangan.
      error.value =
        e instanceof TypeError
          ? "Tidak dapat terhubung ke server. Pastikan backend sedang berjalan."
          : e.message || "Login gagal";
      clearSession();
      return false;
    } finally {
      isLoading.value = false;
    }
  }

  async function logout() {
    const token = refreshToken.value;
    clearSession();
    // Cabut juga hak kirim perintah pada koneksi yang sedang terbuka — tanpa ini
    // tab yang sudah logout masih bisa meng-ARM kapal sampai socketnya putus.
    refreshSocketAuth();
    if (!token) return;
    try {
      await fetch(`${API_BASE}/api/v1/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: token }),
      });
    } catch {
      // Sesi lokal sudah dibersihkan; kegagalan revoke di server tidak memblokir logout.
    }
  }

  // Ambil profil user yang sedang login (GET /users/me).
  async function fetchProfile() {
    if (!accessToken.value) return null;
    try {
      const res = await fetch(`${API_BASE}/api/v1/users/me`, { headers: authHeader() });
      const body = await res.json().catch(() => null);
      if (!res.ok || !body?.success) {
        if (res.status === 401) clearSession();
        return null;
      }
      user.value = body.data;
      persist();
      return user.value;
    } catch {
      return null;
    }
  }

  // Tukar refresh token dengan access token baru saat access token kedaluwarsa.
  async function refreshSession() {
    if (!refreshToken.value) return false;
    try {
      const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken.value }),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok || !body?.success) {
        clearSession();
        return false;
      }
      accessToken.value = body.data.access_token;
      refreshToken.value = body.data.refresh_token;
      persist();
      scheduleRefresh();
      refreshSocketAuth();
      return true;
    } catch {
      return false;
    }
  }

  return {
    user,
    accessToken,
    refreshToken,
    isLoading,
    error,
    isAuthenticated,
    isAdmin,
    authHeader,
    login,
    logout,
    fetchProfile,
    refreshSession,
    ensureFreshSession,
    scheduleRefresh,
    clearSession,
  };
});
