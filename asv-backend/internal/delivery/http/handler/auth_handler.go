package handler

import (
	"go-fiber-template/internal/dto"
	"go-fiber-template/internal/service"
	"go-fiber-template/internal/utils"
	"go-fiber-template/pkg/response"

	ut "github.com/go-playground/universal-translator"
	"github.com/go-playground/validator/v10"
	"github.com/gofiber/fiber/v2"
)

type AuthHandler struct {
	authService service.AuthService
	validator   *validator.Validate
	translator  ut.Translator
}

func NewAuthHandler(authService service.AuthService, validator *validator.Validate, translator ut.Translator) *AuthHandler {
	return &AuthHandler{
		authService: authService,
		validator:   validator,
		translator:  translator,
	}
}

// @Summary Login User
// @Description Authenticate user and return tokens
// @Tags Auth
// @Accept json
// @Produce json
// @Param body body dto.LoginRequest true "Login request"
// @Success 200 {object} response.SwaggerSuccess
// @Failure 401 {object} response.ErrorResponse
// @Router /api/v1/auth/login [post]
func (h *AuthHandler) Login(c *fiber.Ctx) error {
	var req dto.LoginRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid request payload", response.ErrorDetail{Field: "body", Message: err.Error()}))
	}

	if err := h.validator.Struct(req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.ValidationError(err, h.translator))
	}

	resp, err := h.authService.Login(c.UserContext(), &req)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, err.Error()))
	}

	return c.JSON(response.Success("Login successful", fiber.StatusOK, resp))
}

// @Summary Register User
// @Description Register a new user
// @Tags Auth
// @Accept json
// @Produce json
// @Param body body dto.RegisterRequest true "Register request"
// @Success 201 {object} response.SwaggerSuccess
// @Failure 400,500 {object} response.ErrorResponse
// @Router /api/v1/auth/register [post]
func (h *AuthHandler) Register(c *fiber.Ctx) error {
	var req dto.RegisterRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid request payload", response.ErrorDetail{Field: "body", Message: err.Error()}))
	}

	if err := h.validator.Struct(req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.ValidationError(err, h.translator))
	}

	resp, err := h.authService.Register(c.UserContext(), &req)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, err.Error()))
	}

	return c.Status(fiber.StatusCreated).JSON(response.Success("Registration successful", fiber.StatusOK, resp))
}

// @Summary Refresh Token
// @Description Refresh the user's access token
// @Tags Auth
// @Accept json
// @Produce json
// @Param body body dto.RefreshTokenRequest true "Refresh token request"
// @Success 200 {object} response.SwaggerSuccess
// @Failure 400,401 {object} response.ErrorResponse
// @Router /api/v1/auth/refresh [post]
func (h *AuthHandler) RefreshToken(c *fiber.Ctx) error {
	var req dto.RefreshTokenRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid request payload", response.ErrorDetail{Field: "body", Message: err.Error()}))
	}

	resp, err := h.authService.RefreshToken(c.UserContext(), &req)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, err.Error()))
	}

	return c.JSON(response.Success("Token refreshed", fiber.StatusOK, resp))
}

// @Summary Logout User
// @Description Logout a user by invalidating their refresh token
// @Tags Auth
// @Accept json
// @Produce json
// @Param body body dto.LogoutRequest true "Logout request"
// @Success 200 {object} response.SuccessResponse
// @Failure 400,500 {object} response.ErrorResponse
// @Router /api/v1/auth/logout [post]
func (h *AuthHandler) Logout(c *fiber.Ctx) error {
	var req dto.LogoutRequest
	if err := c.BodyParser(&req); err != nil {
		return c.Status(fiber.StatusBadRequest).JSON(response.Error(fiber.StatusBadRequest, "Invalid request payload", response.ErrorDetail{Field: "body", Message: err.Error()}))
	}

	err := h.authService.Logout(c.UserContext(), req.RefreshToken)
	if err != nil {
		statusCode := utils.GetStatusCode(err)
		return c.Status(statusCode).JSON(response.Error(statusCode, err.Error()))
	}

	return c.JSON(response.Success("Logout successful", fiber.StatusOK, nil))
}
