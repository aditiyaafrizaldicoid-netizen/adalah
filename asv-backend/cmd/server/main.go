package main

import (
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	_ "go-fiber-template/docs"
	"go-fiber-template/internal/config"
	"go-fiber-template/internal/delivery/http/handler"
	"go-fiber-template/internal/delivery/http/route"
	"go-fiber-template/internal/middleware"
	"go-fiber-template/internal/repository"
	"go-fiber-template/internal/service"

	"github.com/casbin/casbin/v2"
	"go.uber.org/zap"
)

// @title Go Fiber Clean Architecture API
// @version 1.0
// @description This is a sample swagger for Go Fiber template
// @termsOfService http://swagger.io/terms/

// @contact.name API Support
// @contact.url http://www.swagger.io/support
// @contact.email support@swagger.io

// @license.name Apache 2.0
// @license.url http://www.apache.org/licenses/LICENSE-2.0.html

// @host localhost:3000
// @BasePath /
// @schemes http

// @securityDefinitions.apikey ApiKeyAuth
// @in header
// @name Authorization

func main() {
	// 1. Initialize Configuration (Viper)
	v, err := config.NewViper(".")
	if err != nil {
		panic(fmt.Sprintf("Failed to initialize viper: %v", err))
	}

	cfg, err := config.NewConfig(v)
	if err != nil {
		panic(fmt.Sprintf("Failed to load configuration: %v", err))
	}

	// 2. Initialize Logger
	logger := config.NewLogger(cfg)
	defer logger.Sync()

	// 3. Initialize Database
	db := config.NewDatabase(cfg, logger)

	// 3.5 Selaraskan skema dengan entity, lalu laporkan sisa yang tidak sinkron.
	// Deploy tanpa migrasi dulu muncul sebagai HTTP 500 tanpa penjelasan saat
	// menyimpan setelan; lihat config.SelaraskanSkema.
	config.SelaraskanSkema(db, logger)

	// 4. Initialize Validator
	validator, translator := config.NewValidator()

	// 4.5 Initialize Redis (Flexible Configuration)
	redisClient := config.NewRedisClient(cfg, logger)
	if redisClient != nil {
		defer redisClient.Close()
	}

	// 4.6 Initialize Casbin RBAC
	enforcer, err := casbin.NewEnforcer("casbin/rbac_model.conf", "casbin/policy.csv")
	if err != nil {
		logger.Fatal("Failed to initialize Casbin enforcer", zap.Error(err))
	}

	// 5. Initialize Repositories
	userRepo := repository.NewUserRepository(db, logger)
	tokenRepo := repository.NewRefreshTokenRepository(db, logger)
	asvConfigRepo := repository.NewAsvConfigRepository(db, logger)
	calibRepo := repository.NewCalibrationProfileRepository(db, logger)
	pidConfigRepo := repository.NewPidConfigRepository(db, logger)
	missionPresetRepo := repository.NewMissionPresetRepository(db, logger)
	arenaRepo := repository.NewArenaRepository(db, logger)

	// 6. Initialize Services
	userService := service.NewUserService(userRepo, logger)
	authService := service.NewAuthService(userRepo, tokenRepo, cfg, logger)
	asvConfigService := service.NewAsvConfigService(asvConfigRepo, logger)
	calibService := service.NewCalibrationProfileService(calibRepo, logger)
	pidConfigService := service.NewPidConfigService(pidConfigRepo, logger)
	missionPresetService := service.NewMissionPresetService(missionPresetRepo, logger)
	arenaService := service.NewArenaService(arenaRepo, logger)

	// 7. Initialize Middlewares
	mid := middleware.NewMiddleware(cfg, logger, enforcer)

	// 8. Initialize Handlers
	userHandler := handler.NewUserHandler(userService, validator, translator)
	authHandler := handler.NewAuthHandler(authService, validator, translator)
	healthHandler := handler.NewHealthHandler(db, redisClient)

	wsHub := handler.NewWSHub()
	wsHandler := handler.NewWSHandler(wsHub, cfg, asvConfigService, pidConfigService)
	videoHandler := handler.NewVideoHandler(cfg)
	calibHandler := handler.NewCalibrationProfileHandler(calibService)
	pidConfigHandler := handler.NewPidConfigHandler(pidConfigService)
	missionPresetHandler := handler.NewMissionPresetHandler(missionPresetService)
	sessionHandler := handler.NewSessionHandler()
	arenaHandler := handler.NewArenaHandler(arenaService)
	captureHandler := handler.NewCaptureHandler(cfg)

	// 9. Initialize Router & Get App
	r := route.NewRouter(cfg, mid, authHandler, userHandler, healthHandler, wsHandler, videoHandler, calibHandler, pidConfigHandler, missionPresetHandler, sessionHandler, arenaHandler, captureHandler)

	app := r.New()

	// 10. Start Server
	serverPort := fmt.Sprintf(":%d", cfg.App.Port)

	// Graceful Shutdown Channel
	go func() {
		logger.Info("Starting Web Server", zap.String("port", serverPort))
		if err := app.Listen(serverPort); err != nil {
			logger.Fatal("Failed to start server", zap.Error(err))
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	logger.Info("Gracefully shutting down server...")

	if err := app.ShutdownWithTimeout(10 * time.Second); err != nil {
		logger.Error("Failed to shutdown gracefully", zap.Error(err))
	}

	sqlDB, err := db.DB()
	if err == nil {
		sqlDB.Close()
	}

	logger.Info("Server was successfully shutdown.")
}
