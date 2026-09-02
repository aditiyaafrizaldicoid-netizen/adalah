package config

import (
	"fmt"
	"testing"

	"github.com/stretchr/testify/assert"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// tabelUjiSkema hanya dipakai test ini. Kolomnya sengaja dihapus lalu dipulihkan,
// jadi tidak boleh menumpang tabel aplikasi mana pun — lihat KolomYangHilangUntuk.
type tabelUjiSkema struct {
	ID     uint `gorm:"primaryKey"`
	Ada    string
	Hilang string
}

func (tabelUjiSkema) TableName() string { return "uji_skema_sementara" }

// bukaDBUji menyambung memakai .env di akar modul.
//
// Sambungannya dibuka langsung, bukan lewat NewDatabase, karena NewDatabase memanggil
// logger.Fatal saat gagal — itu mematikan proses test alih-alih mem-skip-nya, sehingga
// `go test ./...` di mesin tanpa Postgres akan gagal padahal tidak ada yang rusak.
func bukaDBUji(t *testing.T) *gorm.DB {
	t.Helper()

	v, err := NewViper("../..")
	if err != nil {
		t.Skipf("konfigurasi tidak terbaca: %v", err)
	}
	cfg, err := NewConfig(v)
	if err != nil {
		t.Skipf("konfigurasi tidak valid: %v", err)
	}
	if cfg.Database.Driver == "mysql" {
		t.Skip("test ini khusus Postgres")
	}

	sslMode := cfg.Database.SSLMode
	if sslMode == "" {
		sslMode = "disable"
	}
	dsn := fmt.Sprintf("host=%s user=%s password=%s dbname=%s port=%d sslmode=%s TimeZone=Asia/Jakarta",
		cfg.Database.Host, cfg.Database.User, cfg.Database.Pass,
		cfg.Database.Name, cfg.Database.Port, sslMode)

	db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{
		Logger: logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		t.Skipf("database uji tidak terjangkau: %v", err)
	}
	return db
}

// TestKolomYangHilangUntuk membuktikan pendeteksian drift skema benar-benar melapor.
//
// Tanpa test ini, cabang "kolom hilang" di SelaraskanSkema gampang jadi kode mati:
// ia cuma berjalan pada keadaan yang jarang, dan kalau logikanya salah, gagalnya
// justru dengan cara diam — persis seperti bug yang melahirkannya.
func TestKolomYangHilangUntuk(t *testing.T) {
	db := bukaDBUji(t)
	models := []any{&tabelUjiSkema{}}

	if err := db.Migrator().DropTable(&tabelUjiSkema{}); err != nil {
		t.Skipf("tidak bisa menyiapkan tabel uji: %v", err)
	}

	// Tabel belum ada sama sekali — kasus deploy ke database yang masih kosong.
	hilang := KolomYangHilangUntuk(db, models)
	assert.Len(t, hilang, 1)
	assert.Contains(t, hilang[0], "uji_skema_sementara")
	assert.Contains(t, hilang[0], "tabel belum dibuat")

	if err := db.AutoMigrate(&tabelUjiSkema{}); err != nil {
		t.Skipf("AutoMigrate gagal, database uji tidak siap: %v", err)
	}
	t.Cleanup(func() { db.Migrator().DropTable(&tabelUjiSkema{}) })

	// Skema yang baru dimigrasi harus bersih. Laporan palsu lebih berbahaya daripada
	// tidak melapor sama sekali: operator akan belajar mengabaikan pesannya.
	assert.Empty(t, KolomYangHilangUntuk(db, models))

	// Tirukan deploy tanpa migrasi: entity punya kolom yang tabelnya belum punya.
	assert.NoError(t, db.Exec("ALTER TABLE uji_skema_sementara DROP COLUMN hilang").Error)

	hilang = KolomYangHilangUntuk(db, models)
	assert.Equal(t, []string{"uji_skema_sementara.hilang"}, hilang,
		"kolom yang hilang harus disebut lengkap dengan nama tabelnya, dan hanya itu")
	assert.Contains(t, RingkasKolomHilang(hilang), "uji_skema_sementara.hilang")

	// Setelah migrasi dijalankan, laporannya bersih lagi — ini yang terjadi saat
	// SelaraskanSkema berhasil menambal skema saat server start.
	assert.NoError(t, db.AutoMigrate(&tabelUjiSkema{}))
	assert.Empty(t, KolomYangHilangUntuk(db, models))
}

func TestRingkasKolomHilang(t *testing.T) {
	assert.Equal(t, "skema sesuai", RingkasKolomHilang(nil))
	assert.Equal(t, "a.b, c.d", RingkasKolomHilang([]string{"a.b", "c.d"}))
}

// TestModelsTerdaftarBisaDiparse menangkap model yang rusak sebelum ia sempat
// membuat KolomYangHilangUntuk melewatkan seluruh tabel diam-diam.
//
// Parse butuh *gorm.DB hasil gorm.Open, bukan struct rakitan: cache skema di dalamnya
// tidak terekspor, dan tanpa itu Parse panik nil-pointer.
func TestModelsTerdaftarBisaDiparse(t *testing.T) {
	db := bukaDBUji(t)

	assert.NotEmpty(t, ModelsTerdaftar())
	for _, m := range ModelsTerdaftar() {
		stmt := &gorm.Statement{DB: db}
		assert.NoError(t, stmt.Parse(m), "model %T harus bisa di-parse GORM", m)
		assert.NotEmpty(t, stmt.Schema.DBNames, "model %T tidak punya kolom", m)
	}
}
