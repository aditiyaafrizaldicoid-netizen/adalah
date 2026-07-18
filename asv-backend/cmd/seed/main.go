package main

import (
	"context"
	"fmt"
	"go-fiber-template/internal/config"
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/utils"
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

	logger.Info("Starting Database Seeding...")

	adminEmail := cfg.Admin.Email
	if adminEmail == "" {
		adminEmail = "admin@mail.com"
	}
	adminPassword := cfg.Admin.Password
	if adminPassword == "" {
		adminPassword = "admin123"
	}

	password, _ := utils.HashPassword(adminPassword)

	admin := entity.User{
		Name:       "Super Admin",
		Email:      adminEmail,
		Password:   password,
		Role:       "admin",
		IsVerified: true,
	}

	user := entity.User{
		Name:       "Normal User",
		Email:      "user@mail.com",
		Password:   password,
		Role:       "user",
		IsVerified: true,
	}

	ctx := context.Background()
	db.WithContext(ctx).Create(&admin)
	db.WithContext(ctx).Create(&user)

	logger.Info(fmt.Sprintf("Database Seeding Completed Successfully! You can now login using %s / %s", adminEmail, adminPassword))
}
