package service

import (
	"go-fiber-template/internal/entity"
)

type CalibrationProfileService interface {
	CreateProfile(profile *entity.CalibrationProfile) error
	UpdateProfile(id uint, profile *entity.CalibrationProfile) error
	DeleteProfile(id uint) error
	GetProfile(id uint) (*entity.CalibrationProfile, error)
	GetAllProfiles() ([]entity.CalibrationProfile, error)
	SetDefaultProfile(id uint) error
}
