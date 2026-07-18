package middleware

import (
	"go-fiber-template/internal/config"
	"github.com/casbin/casbin/v2"
	"go.uber.org/zap"
)

// Middleware struct holds the dependencies for all middlewares.
// Methods attached to this struct act as standard Fiber handlers.
type Middleware struct {
	cfg      *config.Config
	logger   *zap.Logger
	enforcer *casbin.Enforcer
}

// NewMiddleware constructor for DI
func NewMiddleware(cfg *config.Config, logger *zap.Logger, enforcer *casbin.Enforcer) *Middleware {
	return &Middleware{
		cfg:      cfg,
		logger:   logger,
		enforcer: enforcer,
	}
}
