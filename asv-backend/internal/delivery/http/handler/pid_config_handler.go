package handler

import (
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

func (h *PidConfigHandler) SaveConfig(c *fiber.Ctx) error {
	var body entity.PidConfig
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

	if body.Kp != 0 {
		config.Kp = body.Kp
	}
	if body.Ki != 0 {
		config.Ki = body.Ki
	}
	if body.Kd != 0 {
		config.Kd = body.Kd
	}
	if body.ForwardSpeed != 0 {
		config.ForwardSpeed = body.ForwardSpeed
	}
	if body.MaxTurnRate != 0 {
		config.MaxTurnRate = body.MaxTurnRate
	}
	if body.AlignThresholdPx != 0 {
		config.AlignThresholdPx = body.AlignThresholdPx
	}
	if body.MinDetectionAreaPx2 != 0 {
		config.MinDetectionAreaPx2 = body.MinDetectionAreaPx2
	}
	if body.CameraWidth != 0 {
		config.CameraWidth = body.CameraWidth
	}
	if body.CameraHeight != 0 {
		config.CameraHeight = body.CameraHeight
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
