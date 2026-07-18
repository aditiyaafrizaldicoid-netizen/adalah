package config

import (
	"log"

	"github.com/spf13/viper"
)

type Config struct {
	App      AppConfig
	Database DatabaseConfig
	Redis    RedisConfig
	JWT      JWTConfig
	Admin    AdminConfig
}

type AppConfig struct {
	Env        string `mapstructure:"APP_ENV"`
	Port       int    `mapstructure:"APP_PORT"`
	Name       string `mapstructure:"APP_NAME"`
	Showroutes bool   `mapstructure:"APP_SHOW_ROUTES"`
}

type DatabaseConfig struct {
	Driver  string `mapstructure:"DB_DRIVER"`
	Host    string `mapstructure:"DB_HOST"`
	Port    int    `mapstructure:"DB_PORT"`
	User    string `mapstructure:"DB_USER"`
	Pass    string `mapstructure:"DB_PASS"`
	Name    string `mapstructure:"DB_NAME"`
	SSLMode string `mapstructure:"DB_SSLMODE"`
}

type RedisConfig struct {
	Host     string `mapstructure:"REDIS_HOST"`
	Port     int    `mapstructure:"REDIS_PORT"`
	Password string `mapstructure:"REDIS_PASSWORD"`
	DB       int    `mapstructure:"REDIS_DB"`
}

type JWTConfig struct {
	Secret            string `mapstructure:"JWT_SECRET"`
	Expiration        string `mapstructure:"JWT_EXPIRATION"`
	RefreshExpiration string `mapstructure:"JWT_REFRESH_EXPIRATION"`
}

type AdminConfig struct {
	Email    string `mapstructure:"ADMIN_EMAIL"`
	Password string `mapstructure:"ADMIN_PASSWORD"`
}

func NewViper(path string) (*viper.Viper, error) {
	v := viper.New()
	v.SetConfigFile(path + "/.env")
	v.AutomaticEnv()

	if err := v.ReadInConfig(); err != nil {
		log.Printf("Error reading env file, falling back to environment variables: %v", err)
	}

	return v, nil
}

func NewConfig(v *viper.Viper) (*Config, error) {
	var cfg Config

	// Bind environment variables
	v.BindEnv("APP_ENV")
	v.BindEnv("APP_PORT")
	v.BindEnv("APP_NAME")
	v.BindEnv("REDIS_HOST")
	v.BindEnv("REDIS_PORT")
	v.BindEnv("REDIS_PASSWORD")
	v.BindEnv("REDIS_DB")
	v.BindEnv("DB_DRIVER")
	v.BindEnv("DB_HOST")
	v.BindEnv("DB_PORT")
	v.BindEnv("DB_USER")
	v.BindEnv("DB_PASS")
	v.BindEnv("DB_NAME")
	v.BindEnv("DB_SSLMODE")
	v.BindEnv("JWT_SECRET")
	v.BindEnv("JWT_EXPIRATION")
	v.BindEnv("JWT_REFRESH_EXPIRATION")
	v.BindEnv("ADMIN_EMAIL")
	v.BindEnv("ADMIN_PASSWORD")

	if err := v.Unmarshal(&cfg.App); err != nil {
		return nil, err
	}
	if err := v.Unmarshal(&cfg.Database); err != nil {
		return nil, err
	}
	if err := v.Unmarshal(&cfg.Redis); err != nil {
		return nil, err
	}
	if err := v.Unmarshal(&cfg.JWT); err != nil {
		return nil, err
	}
	if err := v.Unmarshal(&cfg.Admin); err != nil {
		return nil, err
	}

	// Set defaults
	if cfg.App.Port == 0 {
		cfg.App.Port = 8080
	}
	if cfg.Redis.Port == 0 && cfg.Redis.Host != "" {
		cfg.Redis.Port = 6379
	}
	if cfg.JWT.Secret == "" {
		cfg.JWT.Secret = "default_secret_key"
	}
	if cfg.JWT.Expiration == "" {
		cfg.JWT.Expiration = "24h"
	}
	if cfg.JWT.RefreshExpiration == "" {
		cfg.JWT.RefreshExpiration = "168h"
	}

	return &cfg, nil
}
