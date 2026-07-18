package service

import (
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/repository"
	"go.uber.org/zap"
)

type calibrationProfileServiceImpl struct {
	repo   repository.CalibrationProfileRepository
	logger *zap.Logger
}

func NewCalibrationProfileService(repo repository.CalibrationProfileRepository, logger *zap.Logger) CalibrationProfileService {
	return &calibrationProfileServiceImpl{
		repo:   repo,
		logger: logger,
	}
}

func (s *calibrationProfileServiceImpl) CreateProfile(profile *entity.CalibrationProfile) error {
	if profile.IsDefault {
		_ = s.repo.ClearDefaultFlags()
	}
	return s.repo.Create(profile)
}

func (s *calibrationProfileServiceImpl) UpdateProfile(id uint, profile *entity.CalibrationProfile) error {
	existing, err := s.repo.FindByID(id)
	if err != nil {
		return err
	}
	
	existing.Name = profile.Name
	existing.ImuProfile = profile.ImuProfile
	existing.GpsOffset = profile.GpsOffset
	existing.CameraSettings = profile.CameraSettings
	existing.ThrusterTrim = profile.ThrusterTrim

	if profile.IsDefault && !existing.IsDefault {
		_ = s.repo.ClearDefaultFlags()
		existing.IsDefault = true
	} else if !profile.IsDefault {
		existing.IsDefault = false
	}

	return s.repo.Update(existing)
}

func (s *calibrationProfileServiceImpl) DeleteProfile(id uint) error {
	return s.repo.Delete(id)
}

func (s *calibrationProfileServiceImpl) GetProfile(id uint) (*entity.CalibrationProfile, error) {
	return s.repo.FindByID(id)
}

func (s *calibrationProfileServiceImpl) GetAllProfiles() ([]entity.CalibrationProfile, error) {
	return s.repo.FindAll()
}

func (s *calibrationProfileServiceImpl) SetDefaultProfile(id uint) error {
	existing, err := s.repo.FindByID(id)
	if err != nil {
		return err
	}
	_ = s.repo.ClearDefaultFlags()
	existing.IsDefault = true
	return s.repo.Update(existing)
}
