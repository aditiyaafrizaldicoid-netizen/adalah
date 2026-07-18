package repository

import (
	"context"
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/utils"

	"go.uber.org/zap"
	"gorm.io/gorm"
)

type userRepositoryImpl struct {
	BaseRepository[entity.User]
	db     *gorm.DB
	logger *zap.Logger
}

func NewUserRepository(db *gorm.DB, logger *zap.Logger) UserRepository {
	return &userRepositoryImpl{
		BaseRepository: NewBaseRepository[entity.User](db, logger),
		db:             db,
		logger:         logger,
	}
}

func (r *userRepositoryImpl) FindByEmail(ctx context.Context, email string) (*entity.User, error) {
	r.logger.Info("Repository: Finding user by email", zap.String("email", email))
	var user entity.User
	if err := r.db.WithContext(ctx).Where("email = ?", email).First(&user).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			r.logger.Warn("Repository: User not found by email", zap.String("email", email))
			return nil, nil
		}
		r.logger.Error("Repository: Failed to find user by email", zap.Error(err), zap.String("email", email))
		return nil, err
	}
	return &user, nil
}

func (r *userRepositoryImpl) FindAll(ctx context.Context, pagination *utils.Pagination) ([]entity.User, int64, error) {
	r.logger.Info("Repository: Finding all users", zap.Int("limit", pagination.Limit), zap.Int("page", pagination.Page))
	var users []entity.User
	var totalRows int64

	query := r.BuildPaginationQuery(r.db.WithContext(ctx), pagination, []string{"name", "email"})

	if err := query.Count(&totalRows).Error; err != nil {
		r.logger.Error("Repository: Failed to count users during FindAll", zap.Error(err))
		return nil, 0, err
	}

	if err := query.Scopes(r.Paginate(pagination)).Find(&users).Error; err != nil {
		r.logger.Error("Repository: Failed to find users during FindAll", zap.Error(err))
		return nil, 0, err
	}

	return users, totalRows, nil
}
