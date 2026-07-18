package repository

import (
	"context"
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/utils"
)

type UserRepository interface {
	BaseRepository[entity.User]
	FindByEmail(ctx context.Context, email string) (*entity.User, error)
	FindAll(ctx context.Context, pagination *utils.Pagination) ([]entity.User, int64, error)
}
