package repository

import (
	"go-fiber-template/internal/entity"

	"go.uber.org/zap"
	"gorm.io/gorm"
)

type PidConfigRepository interface {
	GetConfig() (*entity.PidConfig, error)
	SaveConfig(config *entity.PidConfig) error
}

type pidConfigRepositoryImpl struct {
	db     *gorm.DB
	logger *zap.Logger
}

func NewPidConfigRepository(db *gorm.DB, logger *zap.Logger) PidConfigRepository {
	return &pidConfigRepositoryImpl{
		db:     db,
		logger: logger,
	}
}

func (r *pidConfigRepositoryImpl) GetConfig() (*entity.PidConfig, error) {
	var config entity.PidConfig
	err := r.db.FirstOrCreate(&config, entity.PidConfig{ID: 1}).Error
	if err != nil {
		r.logger.Error("Failed to get PID config from database", zap.Error(err))
		return nil, err
	}
	return &config, nil
}

func (r *pidConfigRepositoryImpl) SaveConfig(config *entity.PidConfig) error {
	config.ID = 1 // Always persist single row
	err := r.db.Save(config).Error
	if err != nil {
		r.logger.Error("Failed to save PID config into database", zap.Error(err))
		return err
	}
	return nil
}
