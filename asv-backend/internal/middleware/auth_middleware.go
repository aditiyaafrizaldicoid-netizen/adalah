package middleware

import (
	"strings"

	"github.com/gofiber/fiber/v2"
	"go-fiber-template/internal/utils"
	"go-fiber-template/pkg/response"
)

func (m *Middleware) AuthMiddleware() fiber.Handler {
	return func(c *fiber.Ctx) error {
		authHeader := c.Get("Authorization")
		if authHeader == "" || !strings.HasPrefix(authHeader, "Bearer ") {
			return c.Status(fiber.StatusUnauthorized).JSON(response.Error(fiber.StatusUnauthorized, "Missing or invalid token format"))
		}

		tokenStr := strings.TrimPrefix(authHeader, "Bearer ")

		claims, err := utils.ValidateJWT(tokenStr, m.cfg.JWT.Secret)
		if err != nil {
			errDetail := response.ErrorDetail{Field: "token", Message: err.Error()}
			return c.Status(fiber.StatusUnauthorized).JSON(response.Error(fiber.StatusUnauthorized, "Invalid or expired token", errDetail))
		}

		c.Locals("user_id", claims["sub"])
		c.Locals("user_role", claims["role"])

		return c.Next()
	}
}
