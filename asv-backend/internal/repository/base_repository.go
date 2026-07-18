package repository

import (
	"context"

	"go-fiber-template/internal/utils"

	"github.com/google/uuid"
	"go.uber.org/zap"
	"gorm.io/gorm"
)

type BaseRepository[T any] interface {
	Create(ctx context.Context, entity *T) error
	Update(ctx context.Context, entity *T) error
	Delete(ctx context.Context, id uuid.UUID) error
	GetByID(ctx context.Context, id uuid.UUID) (*T, error)
	Count(ctx context.Context) (int64, error)
	BuildPaginationQuery(db *gorm.DB, pagination *utils.Pagination, searchFields []string) *gorm.DB
	Paginate(pagination *utils.Pagination) func(db *gorm.DB) *gorm.DB
}

type baseRepositoryImpl[T any] struct {
	db     *gorm.DB
	logger *zap.Logger
}

func NewBaseRepository[T any](db *gorm.DB, logger *zap.Logger) BaseRepository[T] {
	return &baseRepositoryImpl[T]{
		db:     db,
		logger: logger,
	}
}

// Paginate generates the DB Scope function for limits and offsets
func (r *baseRepositoryImpl[T]) Paginate(pagination *utils.Pagination) func(db *gorm.DB) *gorm.DB {
	return func(db *gorm.DB) *gorm.DB {
		orderStr := pagination.SortBy + " " + pagination.Sort
		return db.Offset(pagination.GetOffset()).Limit(pagination.Limit).Order(orderStr)
	}
}
func (r *baseRepositoryImpl[T]) Create(ctx context.Context, entity *T) error {
	r.logger.Info("Repository: Creating entity")
	err := r.db.WithContext(ctx).Create(entity).Error
	if err != nil {
		r.logger.Error("Repository: Failed to create entity", zap.Error(err))
	}
	return err
}

func (r *baseRepositoryImpl[T]) Update(ctx context.Context, entity *T) error {
	r.logger.Info("Repository: Updating entity")
	err := r.db.WithContext(ctx).Save(entity).Error
	if err != nil {
		r.logger.Error("Repository: Failed to update entity", zap.Error(err))
	}
	return err
}

func (r *baseRepositoryImpl[T]) Delete(ctx context.Context, id uuid.UUID) error {
	r.logger.Info("Repository: Deleting entity", zap.String("id", id.String()))
	err := r.db.WithContext(ctx).Delete(new(T), "id = ?", id).Error
	if err != nil {
		r.logger.Error("Repository: Failed to delete entity", zap.Error(err), zap.String("id", id.String()))
	}
	return err
}

func (r *baseRepositoryImpl[T]) GetByID(ctx context.Context, id uuid.UUID) (*T, error) {
	r.logger.Info("Repository: Getting entity by ID", zap.String("id", id.String()))
	var entity T
	if err := r.db.WithContext(ctx).First(&entity, "id = ?", id).Error; err != nil {
		if err == gorm.ErrRecordNotFound {
			r.logger.Warn("Repository: Entity not found", zap.String("id", id.String()))
			return nil, nil
		}
		r.logger.Error("Repository: Failed to get entity by ID", zap.Error(err), zap.String("id", id.String()))
		return nil, err
	}
	return &entity, nil
}

func (r *baseRepositoryImpl[T]) Count(ctx context.Context) (int64, error) {
	r.logger.Info("Repository: Counting entities")
	var total int64
	err := r.db.WithContext(ctx).Model(new(T)).Count(&total).Error
	if err != nil {
		r.logger.Error("Repository: Failed to count entities", zap.Error(err))
	}
	return total, err
}

func (r *baseRepositoryImpl[T]) BuildPaginationQuery(db *gorm.DB, pagination *utils.Pagination, searchFields []string) *gorm.DB {
	query := db.Model(new(T))

	if pagination.Search != "" && len(searchFields) > 0 {
		searchQuery := ""
		likeOperator := "LIKE"
		if db.Dialector.Name() == "postgres" {
			likeOperator = "ILIKE"
		}

		var values []interface{}
		for i, field := range searchFields {
			if i > 0 {
				searchQuery += " OR "
			}
			searchQuery += field + " " + likeOperator + " ?"
			values = append(values, "%"+pagination.Search+"%")
		}
		query = query.Where(searchQuery, values...)
	}

	return query
}
