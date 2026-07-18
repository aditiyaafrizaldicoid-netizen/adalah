package config

import (
	"fmt"
	"go.uber.org/zap"
	"gorm.io/driver/mysql"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
	"log"
	"os"
	"time"
)

// NewDatabase initializes and returns a GORM postgres or mysql connection.
func NewDatabase(cfg *Config, appLogger *zap.Logger) *gorm.DB {
	var dialector gorm.Dialector

	if cfg.Database.Driver == "mysql" {
		dsn := fmt.Sprintf("%s:%s@tcp(%s:%d)/%s?charset=utf8mb4&parseTime=True&loc=Local",
			cfg.Database.User,
			cfg.Database.Pass,
			cfg.Database.Host,
			cfg.Database.Port,
			cfg.Database.Name,
		)
		dialector = mysql.Open(dsn)
	} else {
		sslMode := cfg.Database.SSLMode
		if sslMode == "" {
			sslMode = "disable"
		}
		dsn := fmt.Sprintf("host=%s user=%s password=%s dbname=%s port=%d sslmode=%s TimeZone=Asia/Jakarta",
			cfg.Database.Host,
			cfg.Database.User,
			cfg.Database.Pass,
			cfg.Database.Name,
			cfg.Database.Port,
			sslMode,
		)
		dialector = postgres.Open(dsn)
	}

	// Configure GORM default logger to sync with appEnv
	logLevel := logger.Info
	if cfg.App.Env == "production" {
		logLevel = logger.Error
	}

	newLogger := logger.New(
		log.New(os.Stdout, "\r\n", log.LstdFlags), // io writer
		logger.Config{
			SlowThreshold:             time.Second,
			LogLevel:                  logLevel,
			IgnoreRecordNotFoundError: true,
			Colorful:                  true,
		},
	)

	db, err := gorm.Open(dialector, &gorm.Config{
		Logger: newLogger,
	})
	if err != nil {
		appLogger.Fatal("Failed to connect to database", zap.Error(err))
	}

	appLogger.Info("Database connection successfully established")
	return db
}
