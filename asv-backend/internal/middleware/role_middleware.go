package middleware

import (
	"github.com/gofiber/fiber/v2"
	"go-fiber-template/pkg/response"
)

// RoleMiddleware limits access to specific roles. Assumes Auth middleware ran first.
func (m *Middleware) RoleMiddleware(allowedRoles ...string) fiber.Handler {
	return func(c *fiber.Ctx) error {
		userRole, ok := c.Locals("user_role").(string)
		if !ok {
			return c.Status(fiber.StatusForbidden).JSON(response.Error(fiber.StatusForbidden, "Role not found in context"))
		}

		for _, role := range allowedRoles {
			if userRole == role {
				return c.Next()
			}
		}

		return c.Status(fiber.StatusForbidden).JSON(response.Error(fiber.StatusForbidden, "Insufficient permissions"))
	}
}
