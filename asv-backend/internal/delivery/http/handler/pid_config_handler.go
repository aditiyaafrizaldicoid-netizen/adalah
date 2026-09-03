package handler

import (
	"strings"

	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/service"

	"github.com/gofiber/fiber/v2"
)

type PidConfigHandler struct {
	service service.PidConfigService
}

func NewPidConfigHandler(service service.PidConfigService) *PidConfigHandler {
	return &PidConfigHandler{service: service}
}

func (h *PidConfigHandler) GetConfig(c *fiber.Ctx) error {
	config, err := h.service.GetConfig()
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status":  "error",
			"message": err.Error(),
		})
	}
	return c.JSON(fiber.Map{
		"status": "success",
		"data":   config,
	})
}

// GeofenceRequest memakai POINTER untuk setiap field.
//
// Ini bukan gaya, melainkan keharusan: radius 0 dan enabled=false adalah nilai yang
// SAH dan bermakna "matikan geofence". Pola `if body.X != 0` yang dipakai SaveConfig
// di bawah tidak bisa membedakannya dari "field tidak dikirim", sehingga operator
// tidak akan pernah bisa mematikan geofence dari peta.
type GeofenceRequest struct {
	Enabled *bool    `json:"enabled"`
	Lat     *float64 `json:"lat"`
	Lon     *float64 `json:"lon"`
	RadiusM *float64 `json:"radius_m"`
}

// GetGeofence mengembalikan batas yang tersimpan.
func (h *PidConfigHandler) GetGeofence(c *fiber.Ctx) error {
	config, err := h.service.GetConfig()
	if err != nil || config == nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status": "error", "message": "gagal membaca konfigurasi",
		})
	}
	return c.JSON(fiber.Map{"status": "success", "data": fiber.Map{
		"enabled":  config.GeofenceEnabled,
		"lat":      config.GeofenceLat,
		"lon":      config.GeofenceLon,
		"radius_m": config.GeofenceRadiusM,
	}})
}

// SaveGeofence menyimpan batas yang digambar operator di peta.
func (h *PidConfigHandler) SaveGeofence(c *fiber.Ctx) error {
	var body GeofenceRequest
	if err := c.BodyParser(&body); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status": "error", "message": "Invalid request payload",
		})
	}

	config, err := h.service.GetConfig()
	if err != nil || config == nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status": "error", "message": "gagal membaca konfigurasi",
		})
	}

	if body.Enabled != nil {
		config.GeofenceEnabled = *body.Enabled
	}
	if body.Lat != nil {
		config.GeofenceLat = *body.Lat
	}
	if body.Lon != nil {
		config.GeofenceLon = *body.Lon
	}
	if body.RadiusM != nil {
		if *body.RadiusM < 0 {
			return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
				"status": "error", "message": "radius tidak boleh negatif",
			})
		}
		config.GeofenceRadiusM = *body.RadiusM
	}

	if err := h.service.SaveConfig(config); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status": "error", "message": err.Error(),
		})
	}
	return c.JSON(fiber.Map{"status": "success", "data": fiber.Map{
		"enabled":  config.GeofenceEnabled,
		"lat":      config.GeofenceLat,
		"lon":      config.GeofenceLon,
		"radius_m": config.GeofenceRadiusM,
	}})
}

// PidConfigRequest memakai POINTER untuk setiap field.
//
// KENAPA (bug lapangan): versi sebelumnya mem-parse langsung ke entity.PidConfig
// lalu menyalin field dengan pola `if body.Ki != 0`. Karena nol adalah nilai nol
// Go untuk field yang TIDAK DIKIRIM, pola itu tidak bisa membedakan "tidak
// dikirim" dari "sengaja diisi nol" — sehingga MENYETEL NILAI KE NOL MUSTAHIL.
//
// Itu bukan kasus teoretis. Komentar di control/pid_tracker.py justru menganjurkan
// "Kd sangat kecil / nol" pada 15 FPS, jadi Kd=0 adalah setelan yang memang ingin
// dipakai. Operator mengetik 0, panel menjawab "berhasil disimpan" karena server
// mengembalikan 200, dan nilainya diam-diam tetap seperti semula.
//
// Pointer membuat "tidak dikirim" (nil) berbeda dari "dikirim bernilai 0".
type PidConfigRequest struct {
	Kp                  *float64 `json:"kp"`
	Ki                  *float64 `json:"ki"`
	Kd                  *float64 `json:"kd"`
	ForwardSpeed        *float64 `json:"forward_speed"`
	MaxTurnRate         *float64 `json:"max_turn_rate"`
	AlignThresholdPx    *float64 `json:"align_threshold_px"`
	MinDetectionAreaPx2 *float64 `json:"min_detection_area_px2"`
	CameraWidth         *int     `json:"camera_width"`
	CameraHeight        *int     `json:"camera_height"`
	Track               *string  `json:"track"`
}

// trackValid menormalkan dan memvalidasi nama lintasan.
//
// Ditolak, bukan dibetulkan diam-diam: lintasan yang salah membalik arah setiap
// koreksi kemudi. Nilai yang tidak dikenali jauh lebih baik gagal terang-terangan
// di dashboard daripada tersimpan lalu diabaikan kapal, yang membuat layar dan
// kapal menampilkan dua kenyataan berbeda.
func trackValid(v string) (string, bool) {
	t := strings.ToUpper(strings.TrimSpace(v))
	return t, t == "A" || t == "B"
}

func (h *PidConfigHandler) SaveConfig(c *fiber.Ctx) error {
	var body PidConfigRequest
	if err := c.BodyParser(&body); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid request payload",
		})
	}

	config, err := h.service.GetConfig()
	if err != nil || config == nil {
		config = &entity.PidConfig{}
	}

	if body.Kp != nil {
		config.Kp = *body.Kp
	}
	if body.Ki != nil {
		config.Ki = *body.Ki
	}
	if body.Kd != nil {
		config.Kd = *body.Kd
	}
	if body.ForwardSpeed != nil {
		config.ForwardSpeed = *body.ForwardSpeed
	}
	if body.MaxTurnRate != nil {
		config.MaxTurnRate = *body.MaxTurnRate
	}
	if body.AlignThresholdPx != nil {
		config.AlignThresholdPx = *body.AlignThresholdPx
	}
	if body.MinDetectionAreaPx2 != nil {
		config.MinDetectionAreaPx2 = *body.MinDetectionAreaPx2
	}
	// Resolusi nol akan membuat kamera gagal dibuka di kapal, dan tidak ada
	// keadaan sah yang membutuhkannya — ditolak, bukan diterima diam-diam.
	if body.CameraWidth != nil {
		if *body.CameraWidth <= 0 {
			return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
				"status": "error", "message": "camera_width harus lebih dari 0",
			})
		}
		config.CameraWidth = *body.CameraWidth
	}
	if body.CameraHeight != nil {
		if *body.CameraHeight <= 0 {
			return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
				"status": "error", "message": "camera_height harus lebih dari 0",
			})
		}
		config.CameraHeight = *body.CameraHeight
	}
	if body.Track != nil {
		t, ok := trackValid(*body.Track)
		if !ok {
			return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
				"status": "error", "message": "track harus \"A\" atau \"B\"",
			})
		}
		config.Track = t
	}

	if err := h.service.SaveConfig(config); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status":  "error",
			"message": err.Error(),
		})
	}

	return c.JSON(fiber.Map{
		"status":  "success",
		"message": "PID config saved successfully",
		"data":    config,
	})
}
