package handler_test

import (
	"encoding/json"
	"go-fiber-template/pkg/response"
	"io"
	"net/http/httptest"
	"testing"

	"github.com/gofiber/fiber/v2"
	"github.com/stretchr/testify/assert"
)

// Boilerplate Test Environment setup for Handlers
// Secara best practice, Anda akan menggunakan mockery (github.com/vektra/mockery)
// untuk mock layer service Anda lalu di inject ke NewUserHandler(mockService, mockValidator)

func TestGenericHandlerResponse(t *testing.T) {
	app := fiber.New()

	// Simulasi endpoint
	app.Get("/ping", func(c *fiber.Ctx) error {
		return c.JSON(response.Success("pong", fiber.StatusOK, map[string]string{"status": "ok"}))
	})

	req := httptest.NewRequest("GET", "/ping", nil)
	resp, err := app.Test(req, -1) // Disable timeout

	// 1. Uji tanpa error
	assert.NoError(t, err)

	// 2. Uji status kode adalah 200
	assert.Equal(t, fiber.StatusOK, resp.StatusCode)

	// 3. Uji body JSON menggunakan response.SuccessResponse
	body, _ := io.ReadAll(resp.Body)
	var responseBody response.SuccessResponse
	err = json.Unmarshal(body, &responseBody)

	assert.NoError(t, err)
	assert.True(t, responseBody.Success)
	assert.Equal(t, "pong", responseBody.Message)
}
