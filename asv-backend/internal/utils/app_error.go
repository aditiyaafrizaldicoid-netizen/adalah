package utils

import (
	"github.com/gofiber/fiber/v2"
)

// AppError represents a domain error with an associated HTTP status code
type AppError struct {
	Code    int
	Message string
}

func (e *AppError) Error() string {
	return e.Message
}

// NewError creates a new AppError
func NewError(code int, message string) *AppError {
	return &AppError{
		Code:    code,
		Message: message,
	}
}

// GetStatusCode extracts the HTTP status code from an error.
// If the error is an *AppError, it returns its code.
// Otherwise, it returns 500 (Internal Server Error).
func GetStatusCode(err error) int {
	if err == nil {
		return fiber.StatusOK
	}
	if appErr, ok := err.(*AppError); ok {
		return appErr.Code
	}
	return fiber.StatusInternalServerError
}
