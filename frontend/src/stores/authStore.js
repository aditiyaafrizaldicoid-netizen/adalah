import { defineStore } from "pinia";
import { ref, computed } from "vue";

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:3000";

// Kunci localStorage — dipakai juga oleh router guard saat auth diaktifkan.
const TOKEN_KEY = "asv_access_token";
const REFRESH_KEY = "asv_refresh_token";
const USER_KEY = "asv_user";

function readUser() {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export const useAuthStore = defineStore("auth", () => {
  const user = ref(readUser());
  const accessToken = ref(localStorage.getItem(TOKEN_KEY) || "");
  const refreshToken = ref(localStorage.getItem(REFRESH_KEY) || "");
  const isLoading = ref(false);
  const error = ref("");

  const isAuthenticated = computed(() => !!accessToken.value);
  const isAdmin = computed(() => user.value?.role === "admin");

  function persist() {
    if (accessToken.value) localStorage.setItem(TOKEN_KEY, accessToken.value);
    else localStorage.removeItem(TOKEN_KEY);

    if (refreshToken.value) localStorage.setItem(REFRESH_KEY, refreshToken.value);
    else localStorage.removeItem(REFRESH_KEY);

    if (user.value) localStorage.setItem(USER_KEY, JSON.stringify(user.value));
    else localStorage.removeItem(USER_KEY);
  }

  function clearSession() {
    user.value = null;
    accessToken.value = "";
    refreshToken.value = "";
    persist();
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
    clearSession,
  };
});
