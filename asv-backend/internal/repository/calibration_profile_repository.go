package repository

import (
	"go-fiber-template/internal/entity"

	"go.uber.org/zap"
	"gorm.io/gorm"
)

type CalibrationProfileRepository interface {
	Create(profile *entity.CalibrationProfile) error
	Update(profile *entity.CalibrationProfile) error
	Delete(id uint) error
	FindByID(id uint) (*entity.CalibrationProfile, error)
	FindAll() ([]entity.CalibrationProfile, error)
	ClearDefaultFlags() error
}

type calibrationProfileRepositoryImpl struct {
	db     *gorm.DB
	logger *zap.Logger
}

func NewCalibrationProfileRepository(db *gorm.DB, logger *zap.Logger) CalibrationProfileRepository {
	return &calibrationProfileRepositoryImpl{
		db:     db,
		logger: logger,
	}
}

func (r *calibrationProfileRepositoryImpl) Create(profile *entity.CalibrationProfile) error {
	return r.db.Create(profile).Error
}

func (r *calibrationProfileRepositoryImpl) Update(profile *entity.CalibrationProfile) error {
	return r.db.Save(profile).Error
}

func (r *calibrationProfileRepositoryImpl) Delete(id uint) error {
	return r.db.Delete(&entity.CalibrationProfile{}, id).Error
}

func (r *calibrationProfileRepositoryImpl) FindByID(id uint) (*entity.CalibrationProfile, error) {
	var profile entity.CalibrationProfile
	err := r.db.First(&profile, id).Error
	return &profile, err
}

func (r *calibrationProfileRepositoryImpl) FindAll() ([]entity.CalibrationProfile, error) {
	var profiles []entity.CalibrationProfile
	err := r.db.Order("created_at desc").Find(&profiles).Error
	return profiles, err
}

func (r *calibrationProfileRepositoryImpl) ClearDefaultFlags() error {
	return r.db.Model(&entity.CalibrationProfile{}).Where("is_default = ?", true).Update("is_default", false).Error
}
