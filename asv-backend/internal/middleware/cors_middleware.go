package middleware

import (
	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/fiber/v2/middleware/cors"
)

// CORSMiddleware provides default CORS configuration.
func (m *Middleware) CORSMiddleware() fiber.Handler {
	return cors.New(cors.Config{
		AllowOrigins:     "http://localhost:5173",
		AllowMethods:     "GET,POST,PUT,DELETE,PATCH,OPTIONS",
		AllowCredentials: true,
		AllowHeaders:     "Origin, Content-Type, Accept, Authorization,X-Requested-With,X-CSRF-Token",
	})
}
