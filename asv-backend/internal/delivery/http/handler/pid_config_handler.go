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
