package service

import (
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/repository"

	"go.uber.org/zap"
)

type pidConfigServiceImpl struct {
	repo   repository.PidConfigRepository
	logger *zap.Logger
}

func NewPidConfigService(repo repository.PidConfigRepository, logger *zap.Logger) PidConfigService {
	return &pidConfigServiceImpl{
		repo:   repo,
		logger: logger,
	}
}

func (s *pidConfigServiceImpl) GetConfig() (*entity.PidConfig, error) {
	return s.repo.GetConfig()
}

func (s *pidConfigServiceImpl) SaveConfig(config *entity.PidConfig) error {
	return s.repo.SaveConfig(config)
}
