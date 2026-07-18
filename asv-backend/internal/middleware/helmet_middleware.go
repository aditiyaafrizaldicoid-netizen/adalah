package middleware

import (
	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/fiber/v2/middleware/helmet"
)

// HelmetMiddleware provides default helmet configuration.
func (m *Middleware) HelmetMiddleware() fiber.Handler {
	return helmet.New()
}
