/**
 * Uji lingkaran geofence.
 *
 * Jalankan:  npm test
 *
 * Sebelum migrasi ke Mapbox GL, lingkaran geofence digambar L.circle milik
 * Leaflet — radiusnya meter dan benar tanpa kita pikirkan. Mapbox GL tidak punya
 * padanannya, jadi matematikanya sekarang MILIK KITA, dan kesalahan di sini
 * tidak terlihat seperti error: lingkarannya tetap tergambar rapi, hanya saja
 * ukurannya salah. Operator akan mengira kapal masih di dalam batas padahal
 * sudah keluar — persis kegagalan yang geofence-nya ada untuk mencegah.
 */
import { test, describe } from "node:test";
import assert from "node:assert/strict";

import { lingkaranGeoJSON, koleksiKosong } from "../src/utils/geo.js";

const RADIUS_BUMI_M = 6371008.8;

/** Jarak haversine, ditulis ulang di sini supaya uji tidak memakai kode yang diuji. */
function jarakM(lat1, lng1, lat2, lng2) {
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad;
  const dLng = (lng2 - lng1) * rad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * RADIUS_BUMI_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

// Danau tempat wahana diuji — sengaja bukan (0,0) supaya kesalahan yang hanya
// muncul di lintang tinggi (faktor cos(lat) pada bujur) ikut terjaring.
const LAT = -7.9215169;
const LNG = 112.5973649;

describe("lingkaranGeoJSON", () => {
  test("setiap titik tepat sejauh radius dari pusat", () => {
    const radius = 60;
    const f = lingkaranGeoJSON(LAT, LNG, radius);
    const cincin = f.geometry.coordinates[0];

    for (const [lng, lat] of cincin) {
      const d = jarakM(LAT, LNG, lat, lng);
      // Toleransi 1 cm. Longgar terhadap galat pembulatan floating point,
      // ketat terhadap salah rumus — salah faktor cos(lat) saja sudah meleset
      // belasan meter di lintang ini.
      assert.ok(
        Math.abs(d - radius) < 0.01,
        `jarak ${d} m, seharusnya ${radius} m`
      );
    }
  });

  test("radius besar tetap akurat", () => {
    // Geofence lomba puluhan meter, tapi radius besar menjaring kesalahan yang
    // tersembunyi oleh pendekatan bidang datar pada jarak pendek.
    const radius = 25000;
    const cincin = lingkaranGeoJSON(LAT, LNG, radius).geometry.coordinates[0];
    for (const [lng, lat] of cincin) {
      assert.ok(Math.abs(jarakM(LAT, LNG, lat, lng) - radius) < 0.5);
    }
  });

  test("cincin tertutup — titik terakhir sama dengan yang pertama", () => {
    // Mapbox menolak poligon yang cincinnya tidak tertutup, dan menolaknya
    // dengan cara paling tidak membantu: lingkarannya hilang, konsol bersih.
    const cincin = lingkaranGeoJSON(LAT, LNG, 60).geometry.coordinates[0];
    assert.deepEqual(cincin[0], cincin[cincin.length - 1]);
  });

  test("jumlah titik sesuai segmen, plus satu titik penutup", () => {
    assert.equal(lingkaranGeoJSON(LAT, LNG, 60, 32).geometry.coordinates[0].length, 33);
    assert.equal(lingkaranGeoJSON(LAT, LNG, 60).geometry.coordinates[0].length, 129);
  });

  test("urutan koordinat [lng, lat], bukan [lat, lng]", () => {
    // Kesalahan klasik saat pindah dari Leaflet: Leaflet memakai [lat, lng],
    // GeoJSON dan Mapbox memakai kebalikannya. Tertukar di lintang ini akan
    // melempar geofence ke Samudra Hindia — masih tergambar, hanya tidak
    // terlihat karena berada ribuan kilometer dari kapal.
    const [lng, lat] = lingkaranGeoJSON(LAT, LNG, 60).geometry.coordinates[0][0];
    assert.ok(Math.abs(lng - LNG) < 0.01, `bujur ${lng} tidak dekat ${LNG}`);
    assert.ok(Math.abs(lat - LAT) < 0.01, `lintang ${lat} tidak dekat ${LAT}`);
  });

  test("bentuknya Feature Polygon yang sah", () => {
    const f = lingkaranGeoJSON(LAT, LNG, 60);
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
