package repository

import (
	"go-fiber-template/internal/entity"

	"go.uber.org/zap"
	"gorm.io/gorm"
)

type ArenaRepository interface {
	GetAll() ([]entity.Arena, error)
	GetByID(id uint) (*entity.Arena, error)
	Create(arena *entity.Arena) error
	Update(arena *entity.Arena) error
	Delete(id uint) error
}

type arenaRepository struct {
	db     *gorm.DB
	logger *zap.Logger
}

func NewArenaRepository(db *gorm.DB, logger *zap.Logger) ArenaRepository {
	return &arenaRepository{db: db, logger: logger}
}

func (r *arenaRepository) GetAll() ([]entity.Arena, error) {
	var arenas []entity.Arena
	err := r.db.Order("id desc").Find(&arenas).Error
	return arenas, err
}

func (r *arenaRepository) GetByID(id uint) (*entity.Arena, error) {
	var arena entity.Arena
	err := r.db.First(&arena, id).Error
	if err != nil {
		return nil, err
	}
	return &arena, nil
}

func (r *arenaRepository) Create(arena *entity.Arena) error {
	return r.db.Create(arena).Error
}

func (r *arenaRepository) Update(arena *entity.Arena) error {
	return r.db.Save(arena).Error
}

func (r *arenaRepository) Delete(id uint) error {
	return r.db.Delete(&entity.Arena{}, id).Error
}
