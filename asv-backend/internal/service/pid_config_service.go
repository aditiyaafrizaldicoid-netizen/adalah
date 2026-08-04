package service

import "go-fiber-template/internal/entity"

type PidConfigService interface {
	GetConfig() (*entity.PidConfig, error)
	SaveConfig(config *entity.PidConfig) error
}
