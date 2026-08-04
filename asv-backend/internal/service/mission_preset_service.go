package service

import (
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/repository"

	"go.uber.org/zap"
)

type MissionPresetService interface {
	GetAll() ([]entity.MissionPreset, error)
	GetByID(id uint) (*entity.MissionPreset, error)
	Create(name string, steps string) (*entity.MissionPreset, error)
	Update(id uint, name string, steps string) (*entity.MissionPreset, error)
	Delete(id uint) error
}

type missionPresetService struct {
	repo   repository.MissionPresetRepository
	logger *zap.Logger
}

func NewMissionPresetService(repo repository.MissionPresetRepository, logger *zap.Logger) MissionPresetService {
	return &missionPresetService{repo: repo, logger: logger}
}

func (s *missionPresetService) GetAll() ([]entity.MissionPreset, error) {
	return s.repo.GetAll()
}

func (s *missionPresetService) GetByID(id uint) (*entity.MissionPreset, error) {
	return s.repo.GetByID(id)
}

func (s *missionPresetService) Create(name string, steps string) (*entity.MissionPreset, error) {
	preset := &entity.MissionPreset{
		Name:  name,
		Steps: steps,
	}
	err := s.repo.Create(preset)
	if err != nil {
		s.logger.Error("Failed to create mission preset", zap.Error(err))
		return nil, err
	}
	return preset, nil
}

func (s *missionPresetService) Update(id uint, name string, steps string) (*entity.MissionPreset, error) {
	preset, err := s.repo.GetByID(id)
	if err != nil {
		return nil, err
	}
	if name != "" {
		preset.Name = name
	}
	if steps != "" {
		preset.Steps = steps
	}
	err = s.repo.Update(preset)
	if err != nil {
		s.logger.Error("Failed to update mission preset", zap.Error(err))
		return nil, err
	}
	return preset, nil
}

func (s *missionPresetService) Delete(id uint) error {
	return s.repo.Delete(id)
}
