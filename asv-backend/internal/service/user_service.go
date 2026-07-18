package service

import (
	"context"
	"go-fiber-template/internal/dto"
	"go-fiber-template/internal/utils"

	"github.com/google/uuid"
)

type UserService interface {
	Create(ctx context.Context, req *dto.CreateUserRequest) (*dto.UserResponse, error)
	Update(ctx context.Context, id uuid.UUID, req *dto.UpdateUserRequest) (*dto.UserResponse, error)
	Delete(ctx context.Context, id uuid.UUID) error
	GetByID(ctx context.Context, id uuid.UUID) (*dto.UserResponse, error)
	GetAll(ctx context.Context, pagination *utils.Pagination) ([]dto.UserResponse, int64, error)
	GetUserCount(ctx context.Context) (dto.UserCountResponse, error)
	ActivateAccount(ctx context.Context, id uuid.UUID) error
	DeactivateAccount(ctx context.Context, id uuid.UUID) error
}
