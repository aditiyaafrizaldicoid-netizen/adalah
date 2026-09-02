package config

import (
	"fmt"
	"strings"

	"go-fiber-template/internal/entity"

	"go.uber.org/zap"
	"gorm.io/gorm"
)

// ModelsTerdaftar adalah SATU-SATUNYA daftar tabel yang skemanya dikelola aplikasi.
// cmd/migrate dan pemeriksaan saat start sama-sama membacanya, supaya keduanya tidak
// bisa berbeda isi — dulu daftarnya cuma ada di cmd/migrate.
func ModelsTerdaftar() []any {
	return []any{
		&entity.User{},
		&entity.RefreshToken{},
		&entity.AsvConfig{},
		&entity.CalibrationProfile{},
		&entity.PidConfig{},
		&entity.MissionPreset{},
		&entity.Arena{},
	}
}

// SelaraskanSkema menjalankan AutoMigrate saat server start, lalu melaporkan kolom
// yang masih hilang.
//
// KENAPA ADA (bug lapangan, 2026-09-02): kolom geofence_* ditambahkan ke entity dan
// backend-nya di-deploy, tapi `go run cmd/migrate/main.go` tidak ikut dijalankan.
// Akibatnya sangat menyesatkan karena BACA dan TULIS gagal dengan cara yang berbeda:
//
//	BACA  — `SELECT * FROM pid_configs` tetap sukses. Kolom yang tidak ada hanya
//	        tidak terisi, jadi API menjawab 200 dengan geofence_* bernilai nol.
//	TULIS — `UPDATE pid_configs SET ..., geofence_enabled=...` ditolak seluruhnya
//	        oleh Postgres (SQLSTATE 42703), handler menjawab 500.
//
// Dari sisi operator, dashboard terlihat sehat: nilai Kp bisa diketik, kapal
// menerimanya lewat WebSocket, tapi setiap pindah tab nilainya kembali ke yang lama
// karena penyimpanannya diam-diam tidak pernah berhasil. Tidak ada satu pun pesan
// yang menyebut migrasi. Menjalankan migrasi di sini membuat "deploy" cukup berarti
// "restart", dan drift skema tidak bisa lagi muncul sebagai 500 tanpa penjelasan.
//
// Kegagalan di sini sengaja TIDAK menghentikan server. Backend yang menolak start di
// tepi danau jauh lebih merugikan daripada backend yang sebagian fiturnya gagal:
// telemetri, kendali manual, dan streaming kamera tidak butuh tabel-tabel ini.
// Karena itu kesalahannya dicatat sekeras mungkin, lalu server tetap jalan.
func SelaraskanSkema(db *gorm.DB, logger *zap.Logger) {
	if err := db.AutoMigrate(ModelsTerdaftar()...); err != nil {
		logger.Error("MIGRASI OTOMATIS GAGAL — skema database mungkin tertinggal. "+
			"Penyimpanan setelan (kalibrasi PID, geofence, preset misi) bisa menjawab HTTP 500. "+
			"Jalankan manual: go run cmd/migrate/main.go",
			zap.Error(err))
	}

	if hilang := KolomYangHilang(db); len(hilang) > 0 {
		logger.Error("SKEMA DATABASE TERTINGGAL — kolom berikut tidak ada di tabelnya. "+
			"Setiap penyimpanan ke tabel tersebut akan gagal dengan HTTP 500, "+
			"sementara pembacaannya tetap menjawab 200 dengan nilai nol.",
			zap.Strings("kolom_hilang", hilang))
		return
	}

	logger.Info("Skema database sudah sesuai dengan entity.")
}

// KolomYangHilang membandingkan kolom yang diharapkan entity dengan yang benar-benar
// ada di database. Hasilnya berupa "tabel.kolom" supaya pesan lognya bisa langsung
// ditindaklanjuti tanpa perlu membuka psql.
func KolomYangHilang(db *gorm.DB) []string {
	return KolomYangHilangUntuk(db, ModelsTerdaftar())
}

// KolomYangHilangUntuk memeriksa daftar model yang diberikan.
//
// Daftarnya sengaja jadi parameter, bukan dibaca langsung dari ModelsTerdaftar():
// dengan begitu test-nya bisa memakai tabel bikinan sendiri. Test yang membuktikan
// pendeteksian ini bekerja HARUS menghapus sebuah kolom sungguhan, dan menghapusnya
// dari tabel aplikasi berarti `go test ./...` yang tidak sengaja diarahkan ke
// database produksi akan merusak data setelan.
func KolomYangHilangUntuk(db *gorm.DB, models []any) []string {
	var hilang []string
	migrator := db.Migrator()

	for _, model := range models {
		stmt := &gorm.Statement{DB: db}
		if err := stmt.Parse(model); err != nil {
			// Model yang tidak bisa di-parse adalah bug kode, bukan drift skema.
			// Dilewati saja supaya model lain tetap diperiksa.
			continue
		}

		if !migrator.HasTable(model) {
			hilang = append(hilang, fmt.Sprintf("%s (tabel belum dibuat)", stmt.Table))
			continue
		}

		// DBNames hanya berisi kolom yang benar-benar disimpan — field bertanda
		// `gorm:"-"` dan relasi tidak ikut, jadi tidak ada laporan palsu.
		for _, kolom := range stmt.Schema.DBNames {
			if !migrator.HasColumn(model, kolom) {
				hilang = append(hilang, stmt.Table+"."+kolom)
			}
		}
	}

	return hilang
}

// RingkasKolomHilang memformat hasil KolomYangHilang untuk pesan satu baris.
func RingkasKolomHilang(hilang []string) string {
	if len(hilang) == 0 {
		return "skema sesuai"
	}
	return strings.Join(hilang, ", ")
}
