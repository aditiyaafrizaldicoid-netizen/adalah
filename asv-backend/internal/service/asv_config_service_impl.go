package service

import (
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/repository"
	"go.uber.org/zap"
)

type asvConfigServiceImpl struct {
	repo   repository.AsvConfigRepository
	logger *zap.Logger
}

func NewAsvConfigService(repo repository.AsvConfigRepository, logger *zap.Logger) AsvConfigService {
	return &asvConfigServiceImpl{
		repo:   repo,
		logger: logger,
	}
}

func (s *asvConfigServiceImpl) GetConfig() (*entity.AsvConfig, error) {
	return s.repo.GetConfig()
}

func (s *asvConfigServiceImpl) UpdateConfig(config *entity.AsvConfig) error {
	return s.repo.SaveConfig(config)
}
