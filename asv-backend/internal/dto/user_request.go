package dto

type UpdateProfileRequest struct {
	Name     string `json:"name" validate:"required"`
	Password string `json:"password,omitempty" validate:"omitempty,min=6"`
}

type UpdateUserRequest struct {
	Name     string `json:"name,omitempty" validate:"omitempty"`
	Email    string `json:"email,omitempty" validate:"omitempty,email"`
	Password string `json:"password,omitempty" validate:"omitempty,min=6"`
	Role     string `json:"role,omitempty" validate:"omitempty,oneof=admin user"`
}

type CreateUserRequest struct {
	Name     string `json:"name" validate:"required,min=2,max=100"`
	Email    string `json:"email" validate:"required,email"`
	Password string `json:"password" validate:"required,min=6"`
	Role     string `json:"role" validate:"omitempty,oneof=admin user"`
}
