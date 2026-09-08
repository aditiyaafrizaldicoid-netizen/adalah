/**
 * Satu-satunya tempat frontend membaca kredensial dan gaya peta Mapbox.
 *
 * Polanya sengaja meniru config/api.js: token tidak boleh tersebar di komponen,
 * karena kalau suatu saat harus dirotasi (bocor, kuota habis, ganti akun) yang
 * terlewat baru ketahuan saat peta blank di tengah lomba.
 *
 * Token DIBACA DARI frontend/.env, bukan ditulis di sini. Berkas ini ikut
 * ter-commit; .env tidak (sudah masuk .gitignore). Menaruh token di berkas ini
 * berarti mendorongnya ke riwayat git, dan token yang pernah masuk riwayat harus
 * dianggap bocor selamanya — mencabutnya butuh rewrite history, bukan sekadar
 * commit penghapusan.
 */

// `import.meta.env?.` — bukan langsung: di luar Vite (mis. berkas uji yang
// dijalankan node) `import.meta.env` tidak ada, dan mengaksesnya langsung
// melempar TypeError saat modul dimuat.
export const MAPBOX_TOKEN = import.meta.env?.VITE_MAPBOX_TOKEN || "";

if (!MAPBOX_TOKEN) {
  console.error(
    "[config/mapbox] VITE_MAPBOX_TOKEN belum diset. Isi di frontend/.env lalu " +
      "jalankan ulang dev server — Vite hanya membaca .env saat start, bukan " +
      "saat hot reload. Tanpa token, peta tidak akan memuat tile sama sekali."
  );
}

/**
 * Gaya peta yang tersedia.
 *
 * `satelit` dipakai sebagai bawaan karena operator menilai posisi kapal terhadap
 * garis pantai dan dermaga yang nyata — bukan terhadap label jalan. `gelap`
 * disimpan karena berguna saat lintasan jadi fokus dan citra satelit justru
 * meramaikan latar sehingga garis lintasan sulit diikuti.
 */
export const GAYA_PETA = {
  satelit: "mapbox://styles/mapbox/satellite-streets-v12",
  gelap: "mapbox://styles/mapbox/dark-v11",
};

export const GAYA_BAWAAN = GAYA_PETA.satelit;
