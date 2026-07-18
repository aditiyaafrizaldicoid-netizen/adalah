package handler

import (
	"strconv"

	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/service"

	"github.com/gofiber/fiber/v2"
)

type CalibrationProfileHandler struct {
	service service.CalibrationProfileService
}

func NewCalibrationProfileHandler(s service.CalibrationProfileService) *CalibrationProfileHandler {
	return &CalibrationProfileHandler{
		service: s,
	}
}

func (h *CalibrationProfileHandler) GetAll(c *fiber.Ctx) error {
	profiles, err := h.service.GetAllProfiles()
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error": "Failed to fetch profiles",
		})
	}
	return c.JSON(fiber.Map{
		"data": profiles,
	})
}

func (h *CalibrationProfileHandler) Create(c *fiber.Ctx) error {
	var profile entity.CalibrationProfile
	if err := c.BodyParser(&profile); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error": "Invalid request body",
		})
	}

	if err := h.service.CreateProfile(&profile); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error": "Failed to create profile",
		})
	}

	return c.Status(fiber.StatusCreated).JSON(fiber.Map{
		"data": profile,
	})
}

func (h *CalibrationProfileHandler) Update(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error": "Invalid ID",
		})
	}

	var profile entity.CalibrationProfile
	if err := c.BodyParser(&profile); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error": "Invalid request body",
		})
	}

	if err := h.service.UpdateProfile(uint(id), &profile); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error": "Failed to update profile",
		})
	}

	return c.JSON(fiber.Map{
		"message": "Profile updated successfully",
	})
}

func (h *CalibrationProfileHandler) Delete(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := strconv.ParseUint(idStr, 10, 32)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"error": "Invalid ID",
		})
	}

	if err := h.service.DeleteProfile(uint(id)); err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"error": "Failed to delete profile",
		})
	}

	return c.JSON(fiber.Map{
		"message": "Profile deleted successfully",
	})
}
