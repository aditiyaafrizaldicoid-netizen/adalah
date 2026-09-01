package handler

import (
	"crypto/subtle"
	"encoding/json"
	"io"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"go-fiber-template/internal/config"

	"github.com/gofiber/fiber/v2"
)

// CaptureHandler menyimpan dan menyajikan foto misi ber-geo-tag yang dikirim kapal.
//
// Foto dihasilkan step PHOTO_BOX di Mini PC (control/mission_engine.py →
// camera/geotag.py) dan sebelumnya HANYA tersimpan di disk kapal — untuk melihatnya
// operator harus menyalin berkas dari Mini PC setelah run selesai. Handler ini yang
// membawanya ke base station sehingga bisa muncul di dashboard saat itu juga.
//
// Setiap foto datang berpasangan dengan sidecar JSON berisi field geo-tag yang sama
// dengan yang tercetak di gambar (Day/Date/Time/Coordinate/SOG/COG). Overlay-nya
// sudah terbaca manusia, tapi JSON menyimpan angka mentahnya supaya hasil lomba
// tetap bisa diaudit tanpa membaca piksel.
type CaptureHandler struct {
	cfg *config.Config
	dir string
}

func NewCaptureHandler(cfg *config.Config) *CaptureHandler {
	dir := os.Getenv("CAPTURE_DIR")
	if dir == "" {
		dir = "captures"
	}
	return &CaptureHandler{cfg: cfg, dir: dir}
}

// Nama berkas dari kapal berbentuk 20260901_090316_blue_box.jpg. Pola ketat ini
// dipakai untuk MENOLAK nama lain sama sekali, bukan sekadar membersihkannya:
// endpoint upload-nya menerima berkas dari jaringan, dan satu-satunya penulis yang
// sah punya format yang sangat terduga.
var captureNamePattern = regexp.MustCompile(`^[0-9A-Za-z_\-]{1,80}\.jpg$`)

type CaptureInfo struct {
	Filename string                 `json:"filename"`
	Label    string                 `json:"label"`
	URL      string                 `json:"url"`
	SizeKB   int64                  `json:"size_kb"`
	Geotag   map[string]interface{} `json:"geotag,omitempty"`
}

// Upload menerima satu foto misi dari Mini PC kapal.
//
// Dipagari kunci bersama yang sama dengan /ws/asv dan /video/upload (ASV_WS_TOKEN),
// karena klien Python-nya tidak pernah login. Kalau kunci itu tidak diisi di server,
// endpoint tetap terbuka seperti endpoint kapal lainnya — lihat AppConfig.AsvToken.
func (h *CaptureHandler) Upload(c *fiber.Ctx) error {
	if expected := h.cfg.App.AsvToken; expected != "" {
		if subtle.ConstantTimeCompare([]byte(c.Get("X-ASV-Token")), []byte(expected)) != 1 {
			log.Printf("Upload foto ditolak: X-ASV-Token tidak cocok (ip=%s)", c.IP())
			return c.SendStatus(fiber.StatusUnauthorized)
		}
	}

	file, err := c.FormFile("photo")
	if err != nil {
		return c.Status(400).JSON(fiber.Map{"status": "error", "message": "field 'photo' wajib ada"})
	}

	name := filepath.Base(file.Filename)
	if !captureNamePattern.MatchString(name) {
		return c.Status(400).JSON(fiber.Map{
			"status": "error", "message": "nama berkas tidak valid",
		})
	}

	if err := os.MkdirAll(h.dir, 0o755); err != nil {
		return c.Status(500).JSON(fiber.Map{"status": "error", "message": err.Error()})
	}

	src, err := file.Open()
	if err != nil {
		return c.Status(500).JSON(fiber.Map{"status": "error", "message": err.Error()})
	}
	defer src.Close()

	dst, err := os.Create(filepath.Join(h.dir, name))
	if err != nil {
		return c.Status(500).JSON(fiber.Map{"status": "error", "message": err.Error()})
	}
	defer dst.Close()
	if _, err := io.Copy(dst, src); err != nil {
		return c.Status(500).JSON(fiber.Map{"status": "error", "message": err.Error()})
	}

	// Sidecar geo-tag bersifat opsional: foto yang sampai tanpa metadata tetap jauh
	// lebih berguna daripada upload yang ditolak seluruhnya.
	if meta := c.FormValue("meta"); meta != "" {
		if json.Valid([]byte(meta)) {
			stem := strings.TrimSuffix(name, ".jpg")
			if err := os.WriteFile(filepath.Join(h.dir, stem+".json"), []byte(meta), 0o644); err != nil {
				log.Printf("Gagal menulis sidecar geo-tag untuk %s: %v", name, err)
			}
		} else {
			log.Printf("Sidecar geo-tag untuk %s diabaikan: bukan JSON valid", name)
		}
	}

	log.Printf("📸 Foto misi diterima dari kapal: %s (%d KB)", name, file.Size/1024)
	return c.JSON(fiber.Map{"status": "success", "filename": name})
}

// GetAll mendaftar seluruh foto misi, terbaru di atas.
//
// Publik seperti /video/stream: panel Juri menampilkan foto yang dinilai tanpa
// login, dan gambar tidak bisa membawa header Authorization saat dimuat <img>.
func (h *CaptureHandler) GetAll(c *fiber.Ctx) error {
	entries, err := os.ReadDir(h.dir)
	if err != nil {
		if os.IsNotExist(err) {
			return c.JSON(fiber.Map{"status": "success", "data": []CaptureInfo{}})
		}
		return c.Status(500).JSON(fiber.Map{"status": "error", "message": err.Error()})
	}

	captures := []CaptureInfo{}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".jpg") {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		stem := strings.TrimSuffix(entry.Name(), ".jpg")
		captures = append(captures, CaptureInfo{
			Filename: entry.Name(),
			Label:    labelFromStem(stem),
			URL:      "/api/v1/captures/" + entry.Name(),
			SizeKB:   info.Size() / 1024,
			Geotag:   readSidecar(filepath.Join(h.dir, stem+".json")),
		})
	}

	// Nama berkas diawali stempel waktu (YYYYMMDD_HHMMSS), jadi urutan menurun
	// secara leksikografis = terbaru dulu. Tidak perlu membaca mtime, yang bisa
	// berubah saat berkas disalin antar mesin.
	sort.Slice(captures, func(i, j int) bool {
		return captures[i].Filename > captures[j].Filename
	})

	return c.JSON(fiber.Map{"status": "success", "data": captures})
}

// Download menyajikan satu berkas foto.
func (h *CaptureHandler) Download(c *fiber.Ctx) error {
	name := filepath.Base(c.Params("filename"))
	if !captureNamePattern.MatchString(name) {
		return c.Status(400).JSON(fiber.Map{"status": "error", "message": "nama berkas tidak valid"})
	}
	full := filepath.Join(h.dir, name)
	if _, err := os.Stat(full); os.IsNotExist(err) {
		return c.Status(404).JSON(fiber.Map{"status": "error", "message": "foto tidak ditemukan"})
	}
	return c.SendFile(full)
}

// Delete menghapus satu foto beserta sidecar-nya. Butuh JWT (lihat route.go).
func (h *CaptureHandler) Delete(c *fiber.Ctx) error {
	name := filepath.Base(c.Params("filename"))
	if !captureNamePattern.MatchString(name) {
		return c.Status(400).JSON(fiber.Map{"status": "error", "message": "nama berkas tidak valid"})
	}
	if err := os.Remove(filepath.Join(h.dir, name)); err != nil {
		if os.IsNotExist(err) {
			return c.Status(404).JSON(fiber.Map{"status": "error", "message": "foto tidak ditemukan"})
		}
		return c.Status(500).JSON(fiber.Map{"status": "error", "message": err.Error()})
	}
	// Sidecar menyusul, dan kegagalannya tidak dilaporkan sebagai error: fotonya
	// sudah hilang, jadi permintaan penghapusannya memang sudah terpenuhi.
	_ = os.Remove(filepath.Join(h.dir, strings.TrimSuffix(name, ".jpg")+".json"))
	return c.JSON(fiber.Map{"status": "success", "message": "foto dihapus"})
}

// labelFromStem mengambil label target dari 20260901_090316_blue_box → blue_box.
// Dua ruas pertama selalu tanggal & jam; sisanya label.
func labelFromStem(stem string) string {
	parts := strings.Split(stem, "_")
	if len(parts) >= 3 {
		return strings.Join(parts[2:], "_")
	}
	return ""
}

func readSidecar(path string) map[string]interface{} {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var fields map[string]interface{}
	if err := json.Unmarshal(data, &fields); err != nil {
		return nil
	}
	return fields
}
