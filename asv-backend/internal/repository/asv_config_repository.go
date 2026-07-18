package repository

import (
	"go-fiber-template/internal/entity"

	"go.uber.org/zap"
	"gorm.io/gorm"
)

type AsvConfigRepository interface {
	GetConfig() (*entity.AsvConfig, error)
	SaveConfig(config *entity.AsvConfig) error
}

type asvConfigRepositoryImpl struct {
	db     *gorm.DB
	logger *zap.Logger
}

func NewAsvConfigRepository(db *gorm.DB, logger *zap.Logger) AsvConfigRepository {
	return &asvConfigRepositoryImpl{
		db:     db,
		logger: logger,
	}
}

func (r *asvConfigRepositoryImpl) GetConfig() (*entity.AsvConfig, error) {
	var config entity.AsvConfig
	err := r.db.FirstOrCreate(&config, entity.AsvConfig{ID: 1}).Error
	if err != nil {
		r.logger.Error("Failed to get ASV config", zap.Error(err))
		return nil, err
	}
	return &config, nil
}

func (r *asvConfigRepositoryImpl) SaveConfig(config *entity.AsvConfig) error {
	config.ID = 1 // Ensure we always update the single row
	err := r.db.Save(config).Error
	if err != nil {
		r.logger.Error("Failed to save ASV config", zap.Error(err))
		return err
	}
	return nil
}
