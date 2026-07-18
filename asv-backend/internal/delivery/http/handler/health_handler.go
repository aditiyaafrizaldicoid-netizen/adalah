package handler

import (
	"context"
	"go-fiber-template/pkg/response"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/redis/go-redis/v9"
	"gorm.io/gorm"
)

type HealthHandler struct {
	db    *gorm.DB
	redis *redis.Client
}

func NewHealthHandler(db *gorm.DB, redis *redis.Client) *HealthHandler {
	return &HealthHandler{
		db:    db,
		redis: redis,
	}
}

// HealthCheck handles the health check request with DB and Redis pings
// @Summary Health Check
// @Description Check if the server and its dependencies are alive
// @Tags System
// @Produce json
// @Success 200 {object} response.SuccessResponse
// @Router /api/v1/health [get]
func (h *HealthHandler) HealthCheck(c *fiber.Ctx) error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	status := "healthy"
	details := make(map[string]string)

	// Check Database
	sqlDB, err := h.db.DB()
	if err != nil {
		status = "unhealthy"
		details["database"] = "failed to get db instance"
	} else if err := sqlDB.PingContext(ctx); err != nil {
		status = "unhealthy"
		details["database"] = err.Error()
	} else {
		details["database"] = "connected"
	}

	// Check Redis (if enabled)
	if h.redis != nil {
		if err := h.redis.Ping(ctx).Err(); err != nil {
			// Redis failure doesn't necessarily mean "unhealthy" overall, but we report it
			details["redis"] = err.Error()
		} else {
			details["redis"] = "connected"
		}
	} else {
		details["redis"] = "not configured"
	}

	if status == "unhealthy" {
		return c.Status(fiber.StatusServiceUnavailable).JSON(response.Success("Server is unhealthy", fiber.StatusServiceUnavailable, details))
	}

	return c.JSON(response.Success("Server is healthy", fiber.StatusOK, details))
}
