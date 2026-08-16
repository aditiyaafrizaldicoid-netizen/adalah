package handler

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/gofiber/fiber/v2"
)

// SessionHandler menyajikan daftar dan download file CSV blackbox log dari Python TelemetryLogger.
// File log ditulis oleh flightcontrolAsv1/core/logger.py ke direktori yang dikonfigurasi via LOG_DIR.
type SessionHandler struct {
	logDir string
}

func NewSessionHandler() *SessionHandler {
	logDir := os.Getenv("LOG_DIR")
	if logDir == "" {
		// Default: relatif dari direktori kerja server (biasanya asv-backend/)
		logDir = "../flightcontrolAsv1/logs"
	}
	return &SessionHandler{logDir: logDir}
}

type SessionInfo struct {
	Filename string `json:"filename"`
	Date     string `json:"date"`
	SizeKB   int64  `json:"size_kb"`
	Records  int    `json:"records"` // jumlah baris data (tanpa header)
}

// GetAll godoc
// @Summary List semua session log
// @Tags sessions
// @Produce json
// @Success 200 {object} map[string]interface{}
// @Router /api/v1/sessions [get]
func (h *SessionHandler) GetAll(c *fiber.Ctx) error {
	entries, err := os.ReadDir(h.logDir)
	if err != nil {
		if os.IsNotExist(err) {
			return c.JSON(fiber.Map{"status": "success", "data": []SessionInfo{}})
		}
		return c.Status(500).JSON(fiber.Map{"status": "error", "message": err.Error()})
	}

	sessions := []SessionInfo{}
	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".csv") {
			continue
		}
		info, err := entry.Info()
		if err != nil {
			continue
		}
		records := countCSVRecords(filepath.Join(h.logDir, entry.Name()))
		sessions = append(sessions, SessionInfo{
			Filename: entry.Name(),
			Date:     parseLogDate(entry.Name()),
			SizeKB:   info.Size() / 1024,
			Records:  records,
		})
	}

	// Urutkan terbaru di atas
	sort.Slice(sessions, func(i, j int) bool {
		return sessions[i].Filename > sessions[j].Filename
	})

	return c.JSON(fiber.Map{"status": "success", "data": sessions})
}

// Download godoc
// @Summary Download file CSV session log
// @Tags sessions
// @Param filename path string true "Nama file CSV"
// @Produce octet-stream
// @Success 200
// @Router /api/v1/sessions/{filename} [get]
func (h *SessionHandler) Download(c *fiber.Ctx) error {
	filename := filepath.Base(c.Params("filename")) // cegah path traversal
	if !strings.HasSuffix(filename, ".csv") || strings.Contains(filename, "..") {
		return c.Status(400).JSON(fiber.Map{"status": "error", "message": "invalid filename"})
	}
	fullPath := filepath.Join(h.logDir, filename)
	if _, err := os.Stat(fullPath); os.IsNotExist(err) {
		return c.Status(404).JSON(fiber.Map{"status": "error", "message": "file not found"})
	}
	return c.Download(fullPath, filename)
}

// Delete godoc
// @Summary Hapus file CSV session log
// @Tags sessions
// @Param filename path string true "Nama file CSV"
// @Success 200
// @Router /api/v1/sessions/{filename} [delete]
func (h *SessionHandler) Delete(c *fiber.Ctx) error {
	filename := filepath.Base(c.Params("filename"))
	if !strings.HasSuffix(filename, ".csv") || strings.Contains(filename, "..") {
		return c.Status(400).JSON(fiber.Map{"status": "error", "message": "invalid filename"})
	}
	fullPath := filepath.Join(h.logDir, filename)
	if err := os.Remove(fullPath); err != nil {
		if os.IsNotExist(err) {
			return c.Status(404).JSON(fiber.Map{"status": "error", "message": "file not found"})
		}
		return c.Status(500).JSON(fiber.Map{"status": "error", "message": err.Error()})
	}
	return c.JSON(fiber.Map{"status": "success", "message": "deleted"})
}

// parseLogDate mengurai tanggal dari nama file asv_flight_log_20260816_143022.csv
func parseLogDate(filename string) string {
	name := strings.TrimSuffix(filename, ".csv")
	parts := strings.Split(name, "_")
	if len(parts) >= 2 {
		datePart := parts[len(parts)-2]
		timePart := parts[len(parts)-1]
		if len(datePart) == 8 && len(timePart) == 6 {
			return fmt.Sprintf("%s-%s-%s %s:%s:%s",
				datePart[:4], datePart[4:6], datePart[6:8],
				timePart[:2], timePart[2:4], timePart[4:6],
			)
		}
	}
	return filename
}

// countCSVRecords menghitung jumlah baris data (tidak termasuk header)
func countCSVRecords(path string) int {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0
	}
	lines := strings.Count(string(data), "\n")
	if lines > 0 {
		lines-- // kurangi header
	}
	return lines
}
