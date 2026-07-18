package utils

import (
	"errors"
	"go-fiber-template/pkg/response"

	"github.com/gofiber/fiber/v2"
)

// GlobalErrorHandler handles all errors returned from handlers centrally.
func GlobalErrorHandler(c *fiber.Ctx, err error) error {
	// Status code defaults to 500
	code := fiber.StatusInternalServerError
	message := "Internal Server Error"
	var errDetails []response.ErrorDetail

	// Retrieve the custom status code if it's a fiber.*Error
	var e *fiber.Error
	if errors.As(err, &e) {
		code = e.Code
		message = e.Message
	}

	// Retrieve the custom status code if it's our AppError
	var appErr *AppError
	if errors.As(err, &appErr) {
		code = appErr.Code
		message = appErr.Message
	}

	// Handle Validation Errors if they are returned as raw errors
	// (Though typically we handle them in handlers, this is a fallback)

	// Return JSON response
	return c.Status(code).JSON(response.Error(code, message, errDetails...))
}
