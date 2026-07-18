package handler

import (
	"go-fiber-template/internal/dto"
	"go-fiber-template/internal/service"
	"go-fiber-template/internal/utils"
	"go-fiber-template/pkg/response"

	ut "github.com/go-playground/universal-translator"
	"github.com/go-playground/validator/v10"
	"github.com/gofiber/fiber/v2"
	"github.com/google/uuid"
)

type UserHandler struct {
	userService service.UserService
	validator   *validator.Validate
	translator  ut.Translator
}

func NewUserHandler(userService service.UserService, validator *validator.Validate, translator ut.Translator) *UserHandler {
	return &UserHandler{
		userService: userService,
		validator:   validator,
		translator:  translator,
	}
}

// @Summary Get all users
// @Description Fetch all registered users with pagination
// @Tags Users
// @Accept json
// @Produce json
// @Param page query int false "Page number"
// @Param limit query int false "Page limit"
// @Security ApiKeyAuth
// @Success 200 {object} response.SwaggerPaginated
// @Failure 500 {object} response.ErrorResponse
// @Router /api/v1/users [get]
func (h *UserHandler) GetUsers(c *fiber.Ctx) error {
	pagination := utils.GeneratePaginationFromRequest(c)

	users, total, err := h.userService.GetAll(c.UserContext(), pagination)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, "Failed to fetch users", response.ErrorDetail{Field: "server", Message: err.Error()}))
	}

	return c.JSON(response.SuccessWithPagination("Users retrieved successfully", users, fiber.StatusOK, total, pagination.Limit, pagination.Page))
}

// @Summary Get user by ID
// @Description Fetch a specific user by their ID
// @Tags Users
// @Accept json
// @Produce json
// @Param id path string true "User ID"
// @Security ApiKeyAuth
// @Success 200 {object} response.SwaggerSuccess
// @Failure 400,404,500 {object} response.ErrorResponse
// @Router /api/v1/users/{id} [get]
func (h *UserHandler) GetUserByID(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := uuid.Parse(idStr)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid ID format"))
	}
	user, err := h.userService.GetByID(c.UserContext(), id)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, "Failed to fetch user", response.ErrorDetail{Field: "server", Message: err.Error()}))
	}
	return c.JSON(response.Success("User retrieved successfully", fiber.StatusOK, user))
}

// @Summary Get user count
// @Description Fetch total number of users
// @Tags Users
// @Accept json
// @Produce json
// @Security ApiKeyAuth
// @Success 200 {object} response.SwaggerSuccess
// @Failure 500 {object} response.ErrorResponse
// @Router /api/v1/users/count [get]
func (h *UserHandler) GetUserCount(c *fiber.Ctx) error {
	count, err := h.userService.GetUserCount(c.UserContext())
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, "Failed to fetch user count", response.ErrorDetail{Field: "server", Message: err.Error()}))
	}
	return c.JSON(response.Success("User count retrieved successfully", fiber.StatusOK, count))
}

// @Summary Get user profile
// @Description Fetch the connected user's profile
// @Tags Users
// @Accept json
// @Produce json
// @Security ApiKeyAuth
// @Success 200 {object} response.SwaggerSuccess
// @Failure 401,404 {object} response.ErrorResponse
// @Router /api/v1/users/me [get]
func (h *UserHandler) GetProfile(c *fiber.Ctx) error {
	idStr, ok := c.Locals("user_id").(string)
	if !ok {
		return c.Status(fiber.StatusUnauthorized).JSON(response.Error(fiber.StatusUnauthorized, "Unauthorized"))
	}

	id, err := uuid.Parse(idStr)
	if err != nil {
		return c.Status(fiber.StatusUnauthorized).JSON(response.Error(fiber.StatusUnauthorized, "Invalid ID format in token"))
	}

	user, err := h.userService.GetByID(c.UserContext(), id)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, "User not found"))
	}

	return c.JSON(response.Success("Profile retrieved successfully", fiber.StatusOK, user))
}

// @Summary Update user profile
// @Description Update the connected user's profile
// @Tags Users
// @Accept json
// @Produce json
// @Param body body dto.UpdateProfileRequest true "Update profile request"
// @Security ApiKeyAuth
// @Success 200 {object} response.SwaggerSuccess
// @Failure 400,401,500 {object} response.ErrorResponse
// @Router /api/v1/users/me [put]
func (h *UserHandler) UpdateProfile(c *fiber.Ctx) error {
	idStr, ok := c.Locals("user_id").(string)
	if !ok {
		return c.Status(fiber.StatusUnauthorized).JSON(response.Error(fiber.StatusUnauthorized, "Unauthorized"))
	}

	id, err := uuid.Parse(idStr)
	if err != nil {
		return c.Status(fiber.StatusUnauthorized).JSON(response.Error(fiber.StatusUnauthorized, "Invalid ID format in token"))
	}

	var req dto.UpdateProfileRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid request payload", response.ErrorDetail{Field: "body", Message: err.Error()}))
	}

	if err := h.validator.Struct(req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.ValidationError(err, h.translator))
	}

	// Map UpdateProfileRequest to UpdateUserRequest for service reuse
	updateReq := &dto.UpdateUserRequest{
		Name:     req.Name,
		Password: req.Password,
	}

	user, err := h.userService.Update(c.UserContext(), id, updateReq)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, err.Error()))
	}

	return c.JSON(response.Success("Profile updated successfully", fiber.StatusOK, user))
}

// @Summary Update user by ID
// @Description Update a specific user (Admin only)
// @Tags Users
// @Accept json
// @Produce json
// @Param id path string true "User ID"
// @Param body body dto.UpdateUserRequest true "Update user request"
// @Security ApiKeyAuth
// @Success 200 {object} response.SwaggerSuccess
// @Failure 400,404,500 {object} response.ErrorResponse
// @Router /api/v1/users/{id} [put]
func (h *UserHandler) UpdateUser(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := uuid.Parse(idStr)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid ID format"))
	}

	var req dto.UpdateUserRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid request payload", response.ErrorDetail{Field: "body", Message: err.Error()}))
	}

	if err := h.validator.Struct(req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.ValidationError(err, h.translator))
	}

	user, err := h.userService.Update(c.UserContext(), id, &req)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, err.Error()))
	}

	return c.JSON(response.Success("User updated successfully", fiber.StatusOK, user))
}

// @Summary Delete user
// @Description Delete a specific user (Admin only)
// @Tags Users
// @Accept json
// @Produce json
// @Param id path string true "User ID"
// @Security ApiKeyAuth
// @Success 200 {object} response.SuccessResponse
// @Failure 400,404,500 {object} response.ErrorResponse
// @Router /api/v1/users/{id} [delete]
func (h *UserHandler) DeleteUser(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := uuid.Parse(idStr)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid ID format"))
	}

	err = h.userService.Delete(c.UserContext(), id)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, "Failed to delete user", response.ErrorDetail{Field: "server", Message: err.Error()}))
	}

	return c.JSON(response.Success("User deleted successfully", fiber.StatusOK, nil))
}

// @Summary Activate user account
// @Description Activate a specific user account (Admin only)
// @Tags Users
// @Accept json
// @Produce json
// @Param id path string true "User ID"
// @Security ApiKeyAuth
// @Success 200 {object} response.SuccessResponse
// @Failure 400,404,500 {object} response.ErrorResponse
// @Router /api/v1/users/{id}/activate [patch]
func (h *UserHandler) ActivateAccount(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := uuid.Parse(idStr)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid ID format"))
	}

	if err := h.userService.ActivateAccount(c.UserContext(), id); err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, err.Error()))
	}

	return c.JSON(response.Success("Account activated successfully", fiber.StatusOK, nil))
}

// @Summary Deactivate user account
// @Description Deactivate a specific user account (Admin only)
// @Tags Users
// @Accept json
// @Produce json
// @Param id path string true "User ID"
// @Security ApiKeyAuth
// @Success 200 {object} response.SuccessResponse
// @Failure 400,404,500 {object} response.ErrorResponse
// @Router /api/v1/users/{id}/deactivate [patch]
func (h *UserHandler) DeactivateAccount(c *fiber.Ctx) error {
	idStr := c.Params("id")
	id, err := uuid.Parse(idStr)
	if err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid ID format"))
	}

	if err := h.userService.DeactivateAccount(c.UserContext(), id); err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, err.Error()))
	}

	return c.JSON(response.Success("Account deactivated successfully", fiber.StatusOK, nil))
}
