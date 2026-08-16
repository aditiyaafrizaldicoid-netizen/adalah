package handler

import (
	"strconv"

	"go-fiber-template/internal/service"

	"github.com/gofiber/fiber/v2"
)

type ArenaHandler struct {
	service service.ArenaService
}

func NewArenaHandler(service service.ArenaService) *ArenaHandler {
	return &ArenaHandler{service: service}
}

type ArenaRequest struct {
	Name        string `json:"name"`
	Description string `json:"description"`
	Buoys       string `json:"buoys"`
	Trails      string `json:"trails"`
}

func (h *ArenaHandler) GetAll(c *fiber.Ctx) error {
	arenas, err := h.service.GetAll()
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status":  "error",
			"message": err.Error(),
		})
	}
	return c.JSON(fiber.Map{
		"status": "success",
		"data":   arenas,
	})
}

func (h *ArenaHandler) GetByID(c *fiber.Ctx) error {
	id, err := strconv.ParseUint(c.Params("id"), 10, 32)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid ID format",
		})
	}
	arena, err := h.service.GetByID(uint(id))
	if err != nil {
		return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
			"status":  "error",
			"message": "Arena not found",
		})
	}
	return c.JSON(fiber.Map{"status": "success", "data": arena})
}

func (h *ArenaHandler) Create(c *fiber.Ctx) error {
	var req ArenaRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid request body",
		})
	}
	if req.Name == "" {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Arena name is required",
		})
	}
	arena, err := h.service.Create(req.Name, req.Description, req.Buoys, req.Trails)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status":  "error",
			"message": err.Error(),
		})
	}
	return c.Status(fiber.StatusCreated).JSON(fiber.Map{
		"status":  "success",
		"message": "Arena created successfully",
		"data":    arena,
	})
}

func (h *ArenaHandler) Update(c *fiber.Ctx) error {
	id, err := strconv.ParseUint(c.Params("id"), 10, 32)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid ID format",
		})
	}
	var req ArenaRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(fiber.Map{
			"status":  "error",
			"message": "Invalid request body",
		})
	}
	arena, err := h.service.Update(uint(id), req.Name, req.Description, req.Buoys, req.Trails)
	if err != nil {
		return c.Status(fiber.StatusInternalServerError).JSON(fiber.Map{
			"status":  "error",
			"message": err.Error(),
		})
	}
	return c.JSON(fiber.Map{
		"status":  "success",
		"message": "Arena updated successfully",
		"data":    arena,
	})
}

func (h *ArenaHandler) Delete(c *fiber.Ctx) error {
	id, err := strconv.ParseUint(c.Params("id"), 10, 32)
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
		"message": "Arena deleted successfully",
	})
}
