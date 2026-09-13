/**
 * Uji geometri kotak geofence di sisi peta.
 *
 * Jalankan:  npm test
 *
 * Kotak ini digambar di DUA tempat dengan dua bahasa: di sini (peta) dan di
 * kapal (control/geodesy.py → kotak_batas). Keduanya harus menghasilkan himpunan
 * titik yang SAMA PERSIS. Kalau tidak, peta menggambar satu batas sementara kapal
 * menegakkan batas lain — dan operator tidak punya cara apa pun untuk mengetahuinya:
 * kotaknya tetap tergambar rapi, kapal tetap membatalkan misi, hanya saja di
 * tempat yang berbeda dari yang terlihat.
 *
 * Karena itu ada dua lapis uji di bawah: matematikanya sendiri, DAN kecocokannya
 * dengan angka yang benar-benar dihasilkan kode kapal.
 */
import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  kotakBatas, kotakGeoJSON, marginKotakM, haversineM, koleksiKosong,
} from "../src/utils/geo.js";

// Danau tempat wahana diuji — sengaja bukan (0,0) supaya kesalahan yang hanya
// muncul di lintang tinggi (faktor cos(lat) pada bujur) ikut terjaring.
const LAT = -7.9215169;
const LNG = 112.5973649;

/** Lintang setelah bergerak `meter` ke utara. */
const geserUtara = (lat, meter) => lat + (meter / 6371000) * (180 / Math.PI);
/** Bujur setelah bergerak `meter` ke timur, pada lintang `lat`. */
const geserTimur = (lat, lng, meter) =>
  lng + (meter / (6371000 * Math.cos((lat * Math.PI) / 180))) * (180 / Math.PI);

describe("kotakBatas", () => {
  test("sisi utara-selatan benar-benar setinggi yang diminta", () => {
    const b = kotakBatas(LAT, LNG, 100, 60);
    assert.ok(Math.abs(haversineM(b.latMin, LNG, b.latMaks, LNG) - 60) < 1e-6);
  });

  test("sisi timur-barat benar-benar selebar yang diminta", () => {
    const b = kotakBatas(LAT, LNG, 100, 60);
    assert.ok(Math.abs(haversineM(LAT, b.lonMin, LAT, b.lonMaks) - 100) < 1e-3);
  });

  test("lebar dan tinggi TIDAK tertukar", () => {
    // Kotak 100 × 60 yang sumbunya tertukar tetap tergambar rapi sebagai kotak
    // 60 × 100 — tidak ada error, hanya batas yang salah arah.
    const b = kotakBatas(LAT, LNG, 100, 60);
    assert.ok(haversineM(LAT, b.lonMin, LAT, b.lonMaks) > haversineM(b.latMin, LNG, b.latMaks, LNG),
      "lebar (timur-barat) harus yang 100 m");
  });

  test("simetris terhadap pusat", () => {
    const b = kotakBatas(LAT, LNG, 100, 60);
    assert.ok(Math.abs((b.latMin + b.latMaks) / 2 - LAT) < 1e-12);
    assert.ok(Math.abs((b.lonMin + b.lonMaks) / 2 - LNG) < 1e-12);
  });

  test("bentangan bujur melebar mengikuti lintang", () => {
    // cos(60°) = 0,5 → butuh dua kali lipat derajat bujur untuk jarak yang sama.
    const khat = kotakBatas(0, LNG, 100, 60);
    const tinggi = kotakBatas(60, LNG, 100, 60);
    const rasio = (tinggi.lonMaks - tinggi.lonMin) / (khat.lonMaks - khat.lonMin);
    assert.ok(Math.abs(rasio - 2) < 1e-3, `rasio ${rasio}, harusnya 2`);
  });

  test("bentangan lintang tidak tergantung lintang", () => {
    const a = kotakBatas(0, LNG, 100, 60);
    const b = kotakBatas(60, LNG, 100, 60);
    assert.ok(Math.abs((a.latMaks - a.latMin) - (b.latMaks - b.latMin)) < 1e-12);
  });
});

describe("kecocokan dengan kapal", () => {
  // Angka-angka ini adalah keluaran SUNGGUHAN control/geodesy.py → kotak_batas().
  // Uji ini tidak memeriksa apakah rumusnya benar — itu tugas blok di atas. Yang
  // dijaga di sini adalah agar mengubah SALAH SATU sisi tanpa yang lain langsung
  // ketahuan, bukan baru terlihat sebagai kapal yang dibatalkan di tempat yang
  // tidak sesuai gambar di layar.
  const GOLDEN = [
    { nama: "danau 100×60", lat: -7.9215169, lng: 112.5973649, w: 100, h: 60,
      latMin: -7.921786696481776, latMaks: -7.921247103518224,
      lonMin: 112.59691090709568, lonMaks: 112.59781889290433 },
    { nama: "khatulistiwa 200×200", lat: 0.0, lng: 0.0001, w: 200, h: 200,
      latMin: -0.0008993216059187306, latMaks: 0.0008993216059187306,
      lonMin: -0.0007993216059187305, lonMaks: 0.0009993216059187306 },
    { nama: "lintang tinggi 150×90", lat: 60.0, lng: 10.0, w: 150, h: 90,
      latMin: 59.99959530527734, latMaks: 60.00040469472266,
      lonMin: 9.998651017591122, lonMaks: 10.001348982408878 },
  ];

  for (const g of GOLDEN) {
    test(`${g.nama} sama persis dengan kotak_batas() kapal`, () => {
      const b = kotakBatas(g.lat, g.lng, g.w, g.h);
      for (const k of ["latMin", "latMaks", "lonMin", "lonMaks"]) {
        assert.ok(Math.abs(b[k] - g[k]) < 1e-12,
          `${k}: peta ${b[k]} vs kapal ${g[k]}`);
      }
    });
  }
});

describe("marginKotakM", () => {
  test("di pusat, margin = setengah sisi terpendek", () => {
    assert.ok(Math.abs(marginKotakM(LAT, LNG, 100, 60, LAT, LNG) - 30) < 1e-6);
  });

  test("tepat di dalam dan tepat di luar sisi utara", () => {
    assert.ok(Math.abs(marginKotakM(LAT, LNG, 100, 60, geserUtara(LAT, 29), LNG) - 1) < 0.01);
    assert.ok(Math.abs(marginKotakM(LAT, LNG, 100, 60, geserUtara(LAT, 31), LNG) + 1) < 0.01);
  });

  test("sisi timur memakai setengah LEBAR, bukan tinggi", () => {
    assert.ok(Math.abs(marginKotakM(LAT, LNG, 100, 60, LAT, geserTimur(LAT, LNG, 49)) - 1) < 0.01);
    assert.ok(Math.abs(marginKotakM(LAT, LNG, 100, 60, LAT, geserTimur(LAT, LNG, 51)) + 1) < 0.01);
  });

  test("keluar lewat sudut diukur diagonal", () => {
    // 3 m di luar utara DAN 4 m di luar timur → 5 m, bukan 4 m.
    const d = marginKotakM(LAT, LNG, 100, 60,
      geserUtara(LAT, 33), geserTimur(LAT, LNG, 54));
    assert.ok(Math.abs(d + 5) < 0.01, `margin ${d}, harusnya -5`);
  });

  test("sudut kotak berada DI LUAR lingkaran berjari-jari sama dengan setengah lebar", () => {
    // Inilah beda nyata kotak dan lingkaran, dan alasan FENCE_RADIUS ArduPilot
    // harus disetel ke setengah DIAGONAL, bukan setengah lebar.
    const b = kotakBatas(LAT, LNG, 100, 60);
    const keSudut = haversineM(LAT, LNG, b.latMaks, b.lonMaks);
    assert.ok(keSudut > 50, `jarak ke sudut ${keSudut} m harus > setengah lebar 50 m`);
    assert.ok(Math.abs(keSudut - Math.hypot(100, 60) / 2) < 0.01);
  });
});

describe("kotakGeoJSON", () => {
  test("cincin tertutup — titik terakhir sama dengan yang pertama", () => {
    // Mapbox menolak poligon yang cincinnya tidak tertutup, dan menolaknya
    // dengan cara paling tidak membantu: kotaknya hilang, konsol bersih.
    const c = kotakGeoJSON(LAT, LNG, 100, 60).geometry.coordinates[0];
    assert.deepEqual(c[0], c[c.length - 1]);
  });

  test("empat sudut plus satu penutup", () => {
    assert.equal(kotakGeoJSON(LAT, LNG, 100, 60).geometry.coordinates[0].length, 5);
  });

  test("urutan koordinat [lng, lat], bukan [lat, lng]", () => {
    // Tertukar di lintang ini akan melempar geofence ke Samudra Hindia — masih
    // tergambar, hanya tidak terlihat karena ribuan kilometer dari kapal.
    const [lng, lat] = kotakGeoJSON(LAT, LNG, 100, 60).geometry.coordinates[0][0];
    assert.ok(Math.abs(lng - LNG) < 0.01, `bujur ${lng} tidak dekat ${LNG}`);
    assert.ok(Math.abs(lat - LAT) < 0.01, `lintang ${lat} tidak dekat ${LAT}`);
  });

  test("bentuknya Feature Polygon yang sah", () => {
    const f = kotakGeoJSON(LAT, LNG, 100, 60);
    assert.equal(f.type, "Feature");
    assert.equal(f.geometry.type, "Polygon");
    assert.equal(f.geometry.coordinates.length, 1);
  });
});

describe("koleksiKosong", () => {
  test("FeatureCollection kosong yang sah", () => {
    assert.deepEqual(koleksiKosong(), { type: "FeatureCollection", features: [] });
  });

  test("memberi objek BARU tiap panggilan", () => {
    // Kalau satu objek dipakai bersama, dua source Mapbox yang berbeda akan
    // saling menimpa isinya begitu salah satunya diisi data.
    assert.notEqual(koleksiKosong(), koleksiKosong());
  });
});
