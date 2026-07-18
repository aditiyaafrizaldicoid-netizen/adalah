package repository

import (
	"context"
	"go-fiber-template/internal/entity"

	"github.com/google/uuid"
)

type RefreshTokenRepository interface {
	BaseRepository[entity.RefreshToken]
	FindByToken(ctx context.Context, token string) (*entity.RefreshToken, error)
	DeleteByToken(ctx context.Context, token string) error
	DeleteByUserID(ctx context.Context, userID uuid.UUID) error
}
