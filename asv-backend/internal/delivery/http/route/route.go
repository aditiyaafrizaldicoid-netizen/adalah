package route

import (
	"go-fiber-template/internal/config"
	"go-fiber-template/internal/delivery/http/handler"
	"go-fiber-template/internal/middleware"

	"go-fiber-template/internal/utils"

	"github.com/gofiber/contrib/websocket"
	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/fiber/v2/middleware/requestid"
	"github.com/gofiber/swagger"
)

type Router struct {
	cfg                  *config.Config
	mw                   *middleware.Middleware
	authHandler          *handler.AuthHandler
	userHandler          *handler.UserHandler
	healthHandler        *handler.HealthHandler
	wsHandler            *handler.WSHandler
	videoHandler         *handler.VideoHandler
	calibHandler         *handler.CalibrationProfileHandler
	pidConfigHandler     *handler.PidConfigHandler
	missionPresetHandler *handler.MissionPresetHandler
	sessionHandler       *handler.SessionHandler
}

func NewRouter(
	cfg *config.Config,
	mw *middleware.Middleware,
	authHandler *handler.AuthHandler,
	userHandler *handler.UserHandler,
	healthHandler *handler.HealthHandler,
	wsHandler *handler.WSHandler,
	videoHandler *handler.VideoHandler,
	calibHandler *handler.CalibrationProfileHandler,
	pidConfigHandler *handler.PidConfigHandler,
	missionPresetHandler *handler.MissionPresetHandler,
	sessionHandler *handler.SessionHandler,
) *Router {
	return &Router{
		cfg:                  cfg,
		mw:                   mw,
		authHandler:          authHandler,
		userHandler:          userHandler,
		healthHandler:        healthHandler,
		wsHandler:            wsHandler,
		videoHandler:         videoHandler,
		calibHandler:         calibHandler,
		pidConfigHandler:     pidConfigHandler,
		missionPresetHandler: missionPresetHandler,
		sessionHandler:       sessionHandler,
	}
}

func (r *Router) New() *fiber.App {
	app := fiber.New(fiber.Config{
		AppName:           r.cfg.App.Name,
		EnablePrintRoutes: r.cfg.App.Showroutes,
		ErrorHandler:      utils.GlobalErrorHandler,
	})

	// Global middleware
	if r.mw != nil {
		app.Use(requestid.New())
		app.Use(r.mw.LoggingMiddleware())
		app.Use(r.mw.CORSMiddleware())
	}

	app.Get("/swagger/*", swagger.HandlerDefault)

	api := app.Group("/api/v1")
	// Public: Health Check
	api.Get("/health", r.healthHandler.HealthCheck)
	// Auth Routes
	auth := api.Group("/auth")
	auth.Post("/register", r.authHandler.Register)
	auth.Post("/login", r.authHandler.Login)
	auth.Post("/refresh", r.authHandler.RefreshToken)
	auth.Post("/logout", r.authHandler.Logout)

	// Protected: Users
	users := api.Group("/users", r.mw.AuthMiddleware(), r.mw.CasbinMiddleware())
	users.Get("/me", r.userHandler.GetProfile)
	users.Put("/me", r.userHandler.UpdateProfile)

	// Admin Only: Users Management
	admin := api.Group("/users", r.mw.AuthMiddleware(), r.mw.RoleMiddleware("admin"), r.mw.CasbinMiddleware())
	admin.Get("", r.userHandler.GetUsers)
	admin.Get("/:id", r.userHandler.GetUserByID)
	admin.Get("/user/count", r.userHandler.GetUserCount)
	admin.Put("/:id", r.userHandler.UpdateUser)
	admin.Delete("/:id", r.userHandler.DeleteUser)
	admin.Patch("/:id/activate", r.userHandler.ActivateAccount)
	admin.Patch("/:id/deactivate", r.userHandler.DeactivateAccount)

	// WebSocket Routes
	wsGroup := api.Group("/ws", r.wsHandler.Upgrade)
	wsGroup.Get("/asv", websocket.New(r.wsHandler.HandleASV))
	wsGroup.Get("/client", websocket.New(r.wsHandler.HandleWeb))

	// Video Routes
	videoGroup := api.Group("/video")
	videoGroup.Post("/upload", r.videoHandler.UploadFrame)
	videoGroup.Get("/stream", r.videoHandler.StreamHandler)

	// Calibration Profiles Routes
	calibGroup := api.Group("/calibration")
	calibGroup.Get("/profiles", r.calibHandler.GetAll)
	calibGroup.Post("/profiles", r.calibHandler.Create)
	calibGroup.Put("/profiles/:id", r.calibHandler.Update)

	// PID Config Routes
	pidGroup := api.Group("/pid-config")
	pidGroup.Get("", r.pidConfigHandler.GetConfig)
	pidGroup.Put("", r.pidConfigHandler.SaveConfig)

	// Mission Presets Routes
	presetGroup := api.Group("/mission-presets")
	presetGroup.Get("", r.missionPresetHandler.GetAll)
	presetGroup.Get("/:id", r.missionPresetHandler.GetByID)
	presetGroup.Post("", r.missionPresetHandler.Create)
	presetGroup.Put("/:id", r.missionPresetHandler.Update)
	presetGroup.Delete("/:id", r.missionPresetHandler.Delete)

	// Session Log Routes
	sessionGroup := api.Group("/sessions")
	sessionGroup.Get("", r.sessionHandler.GetAll)
	sessionGroup.Get("/:filename", r.sessionHandler.Download)
	sessionGroup.Delete("/:filename", r.sessionHandler.Delete)

	app.Use(r.mw.NotFoundRouteMiddleware())
	return app
}
