package middleware

import (
	"reflect"

	"github.com/gofiber/fiber/v2"
)

func (m *Middleware) NotFoundRouteMiddleware() fiber.Handler {
	return func(c *fiber.Ctx) error {
		v := reflect.ValueOf(c.Route()).Elem()
		useField := v.FieldByName("use")
		if useField.IsValid() && useField.Bool() {
			return c.Status(fiber.StatusNotFound).JSON(fiber.Map{
				"success":    false,
				"statusCode": 404,
				"message":    "Route not found",
			})
		}
		return c.Next()
	}
}
