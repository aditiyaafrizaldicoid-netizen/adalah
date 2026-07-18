package middleware

import (
	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/fiber/v2/middleware/csrf"
)

func (m *Middleware) CSRFMiddleware() fiber.Handler {
	return csrf.New(csrf.Config{
		CookieName:        "X-Csrf-Token",
		CookieSecure:      false,
		CookieHTTPOnly:    true,
		CookieSameSite:    "Lax",
		CookieSessionOnly: true,
		Extractor:         csrf.CsrfFromCookie("X-Csrf-Token"),
		// Session:           sessionStore,
	})
}
