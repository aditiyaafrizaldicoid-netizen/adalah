package main

import (
	"fmt"
	"go-fiber-template/internal/config"
	"go-fiber-template/internal/entity"
	"go.uber.org/zap"
)

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

	logger.Info("Starting Database Migration...")

	err = db.AutoMigrate(
		&entity.User{},
		&entity.RefreshToken{},
	)

	if err != nil {
		logger.Fatal("Failed to run database migrations", zap.Error(err))
	}

	logger.Info("Database Migrations Completed Successfully!")
}
