package middleware

import (
	"fmt"

	"github.com/gofiber/fiber/v2"
	"go-fiber-template/pkg/response"
	"go.uber.org/zap"
)

func (m *Middleware) CasbinMiddleware() fiber.Handler {
	return func(c *fiber.Ctx) error {
		role, ok := c.Locals("user_role").(string)
		if !ok {
			return c.Status(fiber.StatusForbidden).JSON(response.Error(fiber.StatusForbidden, "Role not found in context"))
		}

		obj := c.Path()
		act := c.Method()

		// Enforce casbin rules
		allowed, err := m.enforcer.Enforce(role, obj, act)
		if err != nil {
			m.logger.Error("Casbin enforcement error", zap.Error(err))
			return c.Status(fiber.StatusInternalServerError).JSON(response.Error(fiber.StatusInternalServerError, "Internal server error"))
		}

		if !allowed {
			m.logger.Warn(fmt.Sprintf("Casbin forbidden: role=%s, path=%s, method=%s", role, obj, act))
			return c.Status(fiber.StatusForbidden).JSON(response.Error(fiber.StatusForbidden, "Forbidden by Casbin RBAC"))
		}

		return c.Next()
	}
}
