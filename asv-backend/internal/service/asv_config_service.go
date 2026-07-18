package service

import (
	"go-fiber-template/internal/entity"
)

type AsvConfigService interface {
	GetConfig() (*entity.AsvConfig, error)
	UpdateConfig(config *entity.AsvConfig) error
}
