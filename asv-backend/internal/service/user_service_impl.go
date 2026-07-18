package service

import (
	"context"

	"go-fiber-template/internal/dto"
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/repository"
	"go-fiber-template/internal/utils"

	"github.com/gofiber/fiber/v2"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

type userServiceImpl struct {
	userRepo repository.UserRepository
	logger   *zap.Logger
}

func NewUserService(userRepo repository.UserRepository, logger *zap.Logger) UserService {
	return &userServiceImpl{
		userRepo: userRepo,
		logger:   logger,
	}
}

func (s *userServiceImpl) Create(ctx context.Context, req *dto.CreateUserRequest) (*dto.UserResponse, error) {
	s.logger.Info("Service: Create user called", zap.String("email", req.Email))

	existingUser, _ := s.userRepo.FindByEmail(ctx, req.Email)
	if existingUser != nil {
		s.logger.Warn("Service: Email already exists", zap.String("email", req.Email))
		return nil, utils.NewError(fiber.StatusConflict, "email already registered")
	}

	hash, err := utils.HashPassword(req.Password)
	if err != nil {
		s.logger.Error("Service: Failed to hash password", zap.Error(err))
		return nil, err
	}

	user := &entity.User{
		Name:     req.Name,
		Email:    req.Email,
		Password: hash,
		Role:     req.Role,
	}

	if err := s.userRepo.Create(ctx, user); err != nil {
		s.logger.Error("Service: Failed to save user to database", zap.Error(err))
		return nil, err
	}

	s.logger.Info("Service: User created successfully", zap.String("user_id", user.ID.String()))
	res := dto.ToUserResponse(user)
	return &res, nil
}

func (s *userServiceImpl) GetByID(ctx context.Context, id uuid.UUID) (*dto.UserResponse, error) {
	s.logger.Info("Service: GetByID called", zap.String("user_id", id.String()))

	user, err := s.userRepo.GetByID(ctx, id)
	if err != nil {
		s.logger.Error("Service: Database error in GetByID", zap.Error(err))
		return nil, err
	}
	if user == nil {
		s.logger.Warn("Service: User not found", zap.String("user_id", id.String()))
		return nil, utils.NewError(fiber.StatusNotFound, "user not found")
	}

	res := dto.ToUserResponse(user)
	return &res, nil
}

func (s *userServiceImpl) GetAll(ctx context.Context, pagination *utils.Pagination) ([]dto.UserResponse, int64, error) {
	s.logger.Info("Service: GetAll users called", zap.Int("limit", pagination.Limit), zap.Int("page", pagination.Page))

	users, total, err := s.userRepo.FindAll(ctx, pagination)
	if err != nil {
		s.logger.Error("Service: Failed to fetch users", zap.Error(err))
		return nil, 0, err
	}

	return dto.ToUserResponseList(users), total, nil
}
func (s *userServiceImpl) GetUserCount(ctx context.Context) (dto.UserCountResponse, error) {
	s.logger.Info("Service: GetUserCount called")
	count, err := s.userRepo.Count(ctx)
	if err != nil {
		s.logger.Error("Service: Failed to fetch user count", zap.Error(err))
		return dto.UserCountResponse{}, err
	}
	return dto.UserCountResponse{Count: count}, nil
}

func (s *userServiceImpl) Update(ctx context.Context, id uuid.UUID, req *dto.UpdateUserRequest) (*dto.UserResponse, error) {
	s.logger.Info("Service: Update user called", zap.String("user_id", id.String()))

	user, err := s.userRepo.GetByID(ctx, id)
	if err != nil || user == nil {
		s.logger.Warn("Service: User not found for update", zap.String("user_id", id.String()))
		return nil, utils.NewError(fiber.StatusNotFound, "user not found")
	}

	if req.Name != "" {
		user.Name = req.Name
	}
	if req.Password != "" {
		hash, err := utils.HashPassword(req.Password)
		if err != nil {
			s.logger.Error("Service: Failed to hash password during update", zap.Error(err))
			return nil, err
		}
		user.Password = hash
	}

	if err := s.userRepo.Update(ctx, user); err != nil {
		s.logger.Error("Service: Failed to update user in DB", zap.Error(err))
		return nil, err
	}

	res := dto.ToUserResponse(user)
	return &res, nil
}

func (s *userServiceImpl) Delete(ctx context.Context, id uuid.UUID) error {
	s.logger.Info("Service: Delete user called", zap.String("user_id", id.String()))

	err := s.userRepo.Delete(ctx, id)
	if err != nil {
		s.logger.Error("Service: Failed to delete user", zap.Error(err), zap.String("user_id", id.String()))
		return err
	}

	return nil
}

func (s *userServiceImpl) ActivateAccount(ctx context.Context, id uuid.UUID) error {
	s.logger.Info("Service: ActivateAccount called", zap.String("user_id", id.String()))

	user, err := s.userRepo.GetByID(ctx, id)
	if err != nil || user == nil {
		s.logger.Warn("Service: User not found for activation", zap.String("user_id", id.String()))
		return utils.NewError(fiber.StatusNotFound, "user not found")
	}

	user.IsVerified = true
	if err := s.userRepo.Update(ctx, user); err != nil {
		s.logger.Error("Service: Failed to activate user", zap.Error(err))
		return err
	}

	return nil
}

func (s *userServiceImpl) DeactivateAccount(ctx context.Context, id uuid.UUID) error {
	s.logger.Info("Service: DeactivateAccount called", zap.String("user_id", id.String()))

	user, err := s.userRepo.GetByID(ctx, id)
	if err != nil || user == nil {
		s.logger.Warn("Service: User not found for deactivation", zap.String("user_id", id.String()))
		return utils.NewError(fiber.StatusNotFound, "user not found")
	}

	user.IsVerified = false
	if err := s.userRepo.Update(ctx, user); err != nil {
		s.logger.Error("Service: Failed to deactivate user", zap.Error(err))
		return err
	}

	return nil
}
