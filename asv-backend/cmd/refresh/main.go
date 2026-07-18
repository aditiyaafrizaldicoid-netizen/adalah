package main

import (
	"fmt"
	"go-fiber-template/internal/config"
	"go-fiber-template/internal/entity"
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
	// Safety Check: Prevent running in production or staging
	if cfg.App.Env == "production" || cfg.App.Env == "staging" {
		fmt.Printf("\n[ABORTED] Perintah Refresh dilarang dijalankan di environment: %s\n", cfg.App.Env)
		fmt.Println("Gunakan environment development untuk melakukan reset database.")
		return
	}
	// 2. Initialize Logger
	logger := config.NewLogger(cfg)
	defer logger.Sync()

	// 3. Initialize Database
	db := config.NewDatabase(cfg, logger)

	logger.Info("Starting Database Refresh (Dropping & Recreating Tables)...")

	models := []interface{}{
		&entity.User{},
		&entity.RefreshToken{},
	}

	// Drop tables
	for _, model := range models {
		if db.Migrator().HasTable(model) {
			if err := db.Migrator().DropTable(model); err != nil {
				logger.Error(fmt.Sprintf("Failed to drop table: %v", err))
			} else {
				logger.Info(fmt.Sprintf("Dropped table for %T", model))
			}
		}
	}

	// Migrate tables
	if err := db.AutoMigrate(models...); err != nil {
		logger.Error(fmt.Sprintf("Failed to auto-migrate tables: %v", err))
		panic(err)
	}

	logger.Info("Database Refresh Completed Successfully! You can now run seed again.")
}
