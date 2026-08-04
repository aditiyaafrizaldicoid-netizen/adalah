package handler

import (
	"strconv"

	"go-fiber-template/internal/service"

	"github.com/gofiber/fiber/v2"
)

type MissionPresetHandler struct {
	service service.MissionPresetService
}

func NewMissionPresetHandler(service service.MissionPresetService) *MissionPresetHandler {
	return &MissionPresetHandler{service: service}
}

type CreateMissionPresetRequest struct {
	Name  string `json:"name"`
	Steps string `json:"steps"`
}

type UpdateMissionPresetRequest struct {
	Name  string `json:"name"`
	Steps string `json:"steps"`
}

func (h *MissionPresetHandler) GetAll(c *fiber.Ctx) error {
	presets, err := h.service.GetAll()
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status":  "error",
			"message": err.Error(),
		})
	}
	return c.JSON(fiber.Map{
		"status": "success",
		"data":   presets,
	})
}

func (h *MissionPresetHandler) GetByID(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid ID format",
		})
	}

	preset, err := h.service.GetByID(uint(id))
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"status":  "error",
			"message": "Mission preset not found",
		})
	}
	return c.JSON(fiber.Map{
		"status": "success",
		"data":   preset,
	})
}

func (h *MissionPresetHandler) Create(c *fiber.Ctx) error {
	var req CreateMissionPresetRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid request body",
		})
	}

	preset, err := h.service.Create(req.Name, req.Steps)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status":  "error",
			"message": err.Error(),
		})
	}
	return c.Status(fiber.StatusCreated).JSON(fiber.Map{
		"status":  "success",
		"message": "Mission preset created successfully",
		"data":    preset,
	})
}

func (h *MissionPresetHandler) Update(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid ID format",
		})
	}

	var req UpdateMissionPresetRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid request body",
		})
	}

	preset, err := h.service.Update(uint(id), req.Name, req.Steps)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status":  "error",
			"message": err.Error(),
		})
	}
	return c.JSON(fiber.Map{
		"status":  "success",
		"message": "Mission preset updated successfully",
		"data":    preset,
	})
}

func (h *MissionPresetHandler) Delete(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid ID format",
		})
	}

	if err := h.service.Delete(uint(id)); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status":  "error",
			"message": err.Error(),
		})
	}
	return c.JSON(fiber.Map{
		"status":  "success",
		"message": "Mission preset deleted successfully",
	})
}
