package service

import (
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/repository"

	"go.uber.org/zap"
)

type ArenaService interface {
	GetAll() ([]entity.Arena, error)
	GetByID(id uint) (*entity.Arena, error)
	Create(name, description, buoys, trails string) (*entity.Arena, error)
	Update(id uint, name, description, buoys, trails string) (*entity.Arena, error)
	Delete(id uint) error
}

type arenaService struct {
	repo   repository.ArenaRepository
	logger *zap.Logger
}

func NewArenaService(repo repository.ArenaRepository, logger *zap.Logger) ArenaService {
	return &arenaService{repo: repo, logger: logger}
}

func (s *arenaService) GetAll() ([]entity.Arena, error) {
	return s.repo.GetAll()
}

func (s *arenaService) GetByID(id uint) (*entity.Arena, error) {
	return s.repo.GetByID(id)
}

func (s *arenaService) Create(name, description, buoys, trails string) (*entity.Arena, error) {
	if buoys == "" {
		buoys = "[]"
	}
	if trails == "" {
		trails = "[]"
	}
	arena := &entity.Arena{
		Name:        name,
		Description: description,
		Buoys:       buoys,
		Trails:      trails,
	}
	if err := s.repo.Create(arena); err != nil {
		s.logger.Error("Failed to create arena", zap.Error(err))
		return nil, err
	}
	return arena, nil
}

func (s *arenaService) Update(id uint, name, description, buoys, trails string) (*entity.Arena, error) {
	arena, err := s.repo.GetByID(id)
	if err != nil {
		return nil, err
	}
	if name != "" {
		arena.Name = name
	}
	arena.Description = description
	if buoys != "" {
		arena.Buoys = buoys
	}
	if trails != "" {
		arena.Trails = trails
	}
	if err := s.repo.Update(arena); err != nil {
		s.logger.Error("Failed to update arena", zap.Error(err))
		return nil, err
	}
	return arena, nil
}

func (s *arenaService) Delete(id uint) error {
	return s.repo.Delete(id)
}
