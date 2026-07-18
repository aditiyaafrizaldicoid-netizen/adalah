package middleware

import (
	"time"

	"github.com/gofiber/fiber/v2"
	"go.uber.org/zap"
)

// LoggingMiddleware middleware method
func (m *Middleware) LoggingMiddleware() fiber.Handler {
	return func(c *fiber.Ctx) error {
		start := time.Now()

		// Map next handler
		err := c.Next()

		duration := time.Since(start)

		m.logger.Info("HTTP Request",
			zap.String("request_id", c.Get("X-Request-ID")),
			zap.String("method", c.Method()),
			zap.String("path", c.Path()),
			zap.Int("status", c.Response().StatusCode()),
			zap.String("ip", c.IP()),
			zap.Duration("latency", duration),
			zap.Error(err),
		)

		return err
	}
}

