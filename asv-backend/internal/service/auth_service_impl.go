package service

import (
	"context"
	"go-fiber-template/internal/config"
	"go-fiber-template/internal/dto"
	"go-fiber-template/internal/entity"
	"go-fiber-template/internal/repository"
	"go-fiber-template/internal/utils"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

type authServiceImpl struct {
	userRepo  repository.UserRepository
	tokenRepo repository.RefreshTokenRepository
	cfg       *config.Config
	logger    *zap.Logger
}

func NewAuthService(userRepo repository.UserRepository, tokenRepo repository.RefreshTokenRepository, cfg *config.Config, logger *zap.Logger) AuthService {
	return &authServiceImpl{
		userRepo:  userRepo,
		tokenRepo: tokenRepo,
		cfg:       cfg,
		logger:    logger,
	}
}

func (s *authServiceImpl) Login(ctx context.Context, req *dto.LoginRequest) (*dto.LoginResponse, error) {
	s.logger.Info("Service: Login called", zap.String("email", req.Email))

	user, err := s.userRepo.FindByEmail(ctx, req.Email)
	if err != nil {
		s.logger.Error("Service: Login database error", zap.Error(err), zap.String("email", req.Email))
		return nil, utils.NewError(fiber.StatusUnauthorized, "invalid credentials")
	}
	if user == nil {
		s.logger.Warn("Service: Login user not found", zap.String("email", req.Email))
		return nil, utils.NewError(fiber.StatusUnauthorized, "invalid credentials")
	}

	if !utils.CheckPasswordHash(req.Password, user.Password) {
		s.logger.Warn("Service: Login password mismatch", zap.String("email", req.Email))
		return nil, utils.NewError(fiber.StatusUnauthorized, "invalid credentials")
	}

	if !user.IsVerified {
		s.logger.Warn("Service: Login user not verified", zap.String("email", req.Email))
		return nil, utils.NewError(fiber.StatusUnauthorized, "account not verified")
	}

	accessToken, err := utils.GenerateJWT(user.ID, user.Role, s.cfg.JWT.Secret, s.cfg.JWT.Expiration)
	if err != nil {
		s.logger.Error("Service: Failed to generate access token", zap.Error(err))
		return nil, err
	}

	refreshToken, err := utils.GenerateJWT(user.ID, user.Role, s.cfg.JWT.Secret, s.cfg.JWT.RefreshExpiration)
	if err != nil {
		s.logger.Error("Service: Failed to generate refresh token", zap.Error(err))
		return nil, err
	}

	expiredDuration, _ := time.ParseDuration(s.cfg.JWT.RefreshExpiration)
	rt := &entity.RefreshToken{
		Token:     refreshToken,
		UserID:    user.ID,
		ExpiresAt: time.Now().Add(expiredDuration),
	}

	if err := s.tokenRepo.Create(ctx, rt); err != nil {
		s.logger.Error("Service: Failed to store refresh token", zap.Error(err))
		return nil, err
	}

	s.logger.Info("Service: User logged in successfully", zap.String("user_id", user.ID.String()))
	return &dto.LoginResponse{
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		User:         dto.ToUserResponse(user),
	}, nil
}

func (s *authServiceImpl) Register(ctx context.Context, req *dto.RegisterRequest) (*dto.UserResponse, error) {
	s.logger.Info("Service: Register called", zap.String("email", req.Email))

	existingUser, _ := s.userRepo.FindByEmail(ctx, req.Email)
	if existingUser != nil {
		s.logger.Warn("Service: Registration email already exists", zap.String("email", req.Email))
		return nil, utils.NewError(fiber.StatusConflict, "email already exists")
	}

	hashedPassword, err := utils.HashPassword(req.Password)
	if err != nil {
		s.logger.Error("Service: Registration password hash failed", zap.Error(err))
		return nil, err
	}

	user := &entity.User{
		Name:     req.Name,
		Email:    req.Email,
		Password: hashedPassword,
		Role:     "user",
	}

	if err := s.userRepo.Create(ctx, user); err != nil {
		s.logger.Error("Service: Registration save failed", zap.Error(err))
		return nil, err
	}

	s.logger.Info("Service: User registered successfully", zap.String("user_id", user.ID.String()))
	res := dto.ToUserResponse(user)
	return &res, nil
}

func (s *authServiceImpl) RefreshToken(ctx context.Context, req *dto.RefreshTokenRequest) (*dto.TokenResponse, error) {
	s.logger.Info("Service: RefreshToken called")

	claims, err := utils.ValidateJWT(req.RefreshToken, s.cfg.JWT.Secret)
	if err != nil {
		s.logger.Warn("Service: Invalid refresh token provided", zap.Error(err))
		return nil, utils.NewError(fiber.StatusUnauthorized, "invalid token")
	}

	rt, err := s.tokenRepo.FindByToken(ctx, req.RefreshToken)
	if err != nil || rt == nil {
		s.logger.Warn("Service: Refresh token not found in database")
		return nil, utils.NewError(fiber.StatusUnauthorized, "token not found or revoked")
	}

	if rt.RevokedAt != nil || rt.ExpiresAt.Before(time.Now()) {
		s.logger.Warn("Service: Refresh token expired or revoked")
		return nil, utils.NewError(fiber.StatusUnauthorized, "token expired or revoked")
	}

	userIDStr, _ := claims["sub"].(string)
	userID, _ := uuid.Parse(userIDStr)
	role, _ := claims["role"].(string)

	accessToken, _ := utils.GenerateJWT(userID, role, s.cfg.JWT.Secret, s.cfg.JWT.Expiration)
	newRefreshToken, _ := utils.GenerateJWT(userID, role, s.cfg.JWT.Secret, s.cfg.JWT.RefreshExpiration)

	expiredDuration, _ := time.ParseDuration(s.cfg.JWT.RefreshExpiration)

	newRT := &entity.RefreshToken{
		Token:     newRefreshToken,
		UserID:    userID,
		ExpiresAt: time.Now().Add(expiredDuration),
	}

	if err := s.tokenRepo.Create(ctx, newRT); err != nil {
		s.logger.Error("Service: Failed to store new refresh token", zap.Error(err))
		return nil, err
	}

	// Soft delete old token
	_ = s.tokenRepo.Delete(ctx, rt.ID)

	s.logger.Info("Service: Token refreshed successfully", zap.String("user_id", userID.String()))
	return &dto.TokenResponse{
		AccessToken:  accessToken,
		RefreshToken: newRefreshToken,
	}, nil
}

func (s *authServiceImpl) Logout(ctx context.Context, token string) error {
	s.logger.Info("Service: Logout called")

	rt, err := s.tokenRepo.FindByToken(ctx, token)
	if err != nil || rt == nil {
		s.logger.Warn("Service: Logout token not found")
		return utils.NewError(fiber.StatusUnauthorized, "token not found")
	}

	now := time.Now()
	rt.RevokedAt = &now
	_ = s.tokenRepo.Update(ctx, rt)

	err = s.tokenRepo.Delete(ctx, rt.ID)
	if err != nil {
		s.logger.Error("Service: Logout token deletion failed", zap.Error(err))
	}

	s.logger.Info("Service: Logout successful", zap.String("user_id", rt.UserID.String()))
	return nil
}
