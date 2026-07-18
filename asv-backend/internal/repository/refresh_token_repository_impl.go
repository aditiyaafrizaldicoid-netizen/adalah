package repository

import (
	"context"
	"go-fiber-template/internal/entity"

	"github.com/google/uuid"
	"go.uber.org/zap"
	"gorm.io/gorm"
)

type refreshTokenRepositoryImpl struct {
	BaseRepository[entity.RefreshToken]
	db     *gorm.DB
	logger *zap.Logger
}

func NewRefreshTokenRepository(db *gorm.DB, logger *zap.Logger) RefreshTokenRepository {
	return &refreshTokenRepositoryImpl{
		BaseRepository: NewBaseRepository[entity.RefreshToken](db, logger),
		db:             db,
		logger:         logger,
	}
}

func (r *refreshTokenRepositoryImpl) FindByToken(ctx context.Context, token string) (*entity.RefreshToken, error) {
	r.logger.Info("Repository: Finding refresh token")
	var rt entity.RefreshToken
	if err := r.db.WithContext(ctx).Where("token = ?", token).First(&rt).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			r.logger.Warn("Repository: Refresh token not found")
			return nil, nil
		}
		r.logger.Error("Repository: Failed to find refresh token", zap.Error(err))
		return nil, err
	}
	return &rt, nil
}

func (r *refreshTokenRepositoryImpl) DeleteByToken(ctx context.Context, token string) error {
	r.logger.Info("Repository: Deleting refresh token by string")
	err := r.db.WithContext(ctx).Where("token = ?", token).Delete(&entity.RefreshToken{}).Error
	if err != nil {
		r.logger.Error("Repository: Failed to delete refresh token by string", zap.Error(err))
	}
	return err
}

func (r *refreshTokenRepositoryImpl) DeleteByUserID(ctx context.Context, userID uuid.UUID) error {
	r.logger.Info("Repository: Deleting refresh tokens by UserID", zap.String("user_id", userID.String()))
	err := r.db.WithContext(ctx).Where("user_id = ?", userID).Delete(&entity.RefreshToken{}).Error
	if err != nil {
		r.logger.Error("Repository: Failed to delete refresh tokens by UserID", zap.Error(err), zap.String("user_id", userID.String()))
	}
	return err
}
