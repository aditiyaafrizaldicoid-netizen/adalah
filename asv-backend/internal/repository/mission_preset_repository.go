package repository

import (
	"go-fiber-template/internal/entity"

	"go.uber.org/zap"
	"gorm.io/gorm"
)

type MissionPresetRepository interface {
	GetAll() ([]entity.MissionPreset, error)
	GetByID(id uint) (*entity.MissionPreset, error)
	Create(preset *entity.MissionPreset) error
	Update(preset *entity.MissionPreset) error
	Delete(id uint) error
}

type missionPresetRepository struct {
	db     *gorm.DB
	logger *zap.Logger
}

func NewMissionPresetRepository(db *gorm.DB, logger *zap.Logger) MissionPresetRepository {
	return &missionPresetRepository{db: db, logger: logger}
}

func (r *missionPresetRepository) GetAll() ([]entity.MissionPreset, error) {
	var presets []entity.MissionPreset
	err := r.db.Order("id desc").Find(&presets).Error
	return presets, err
}

func (r *missionPresetRepository) GetByID(id uint) (*entity.MissionPreset, error) {
	var preset entity.MissionPreset
	err := r.db.First(&preset, id).Error
	if err != nil {
		return nil, err
	}
	return &preset, nil
}

func (r *missionPresetRepository) Create(preset *entity.MissionPreset) error {
	return r.db.Create(preset).Error
}

func (r *missionPresetRepository) Update(preset *entity.MissionPreset) error {
	return r.db.Save(preset).Error
}

func (r *missionPresetRepository) Delete(id uint) error {
	return r.db.Delete(&entity.MissionPreset{}, id).Error
}
