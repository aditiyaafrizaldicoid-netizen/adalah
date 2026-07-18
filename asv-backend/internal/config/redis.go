package config

import (
	"context"
	"fmt"

	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

// NewRedisClient initializes a flexible Redis client connection caching.
// It will gracefully degrade (return nil) if REDIS_HOST logic is missing from configuration,
// so the apps will continue running perfectly without requiring Redis.
func NewRedisClient(cfg *Config, logger *zap.Logger) *redis.Client {
	if cfg.Redis.Host == "" {
		logger.Warn("Redis Host is not provided in env, application will proceed without caching layer.")
		return nil
	}

	addr := fmt.Sprintf("%s:%d", cfg.Redis.Host, cfg.Redis.Port)
	client := redis.NewClient(&redis.Options{
		Addr:     addr,
		Password: cfg.Redis.Password,
		DB:       cfg.Redis.DB,
	})

	_, err := client.Ping(context.Background()).Result()
	if err != nil {
		logger.Error("Failed to connect to Redis", zap.Error(err), zap.String("address", addr))
		// Optionally, you could panic here if Redis is supposed to be hard-required, but per user request, it's flexible.
		return nil
	}

	logger.Info("Successfully connected to Redis", zap.String("address", addr))
	return client
}
