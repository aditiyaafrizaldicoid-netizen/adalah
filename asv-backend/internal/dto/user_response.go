package dto

import (
	"time"

	"go-fiber-template/internal/entity"

	"github.com/google/uuid"
)

type UserCountResponse struct {
	Count int64 `json:"count"`
}
type UserResponse struct {
	ID         uuid.UUID `json:"id"`
	Name       string    `json:"name"`
	Email      string    `json:"email"`
	Role       string    `json:"role"`
	IsVerified bool      `json:"is_verified"`
	CreatedAt  time.Time `json:"created_at"`
	UpdatedAt  time.Time `json:"updated_at"`
}

func ToUserResponse(user *entity.User) UserResponse {
	return UserResponse{
		ID:         user.ID,
		Name:       user.Name,
		Email:      user.Email,
		Role:       user.Role,
		IsVerified: user.IsVerified,
		CreatedAt:  user.CreatedAt,
		UpdatedAt:  user.UpdatedAt,
	}
}

func ToUserResponseList(users []entity.User) []UserResponse {
	var responses []UserResponse
	if len(users) == 0 {
		return []UserResponse{}
	}
	for _, user := range users {
		responses = append(responses, ToUserResponse(&user))
	}
	return responses
}
