# Go Fiber v2 Clean Architecture Template

A production-ready REST API template built with Go Fiber v2, GORM, and JWT. This project follows Clean Architecture and Domain-Driven Design (DDD) principles.

## Features

- **Framework**: [Go Fiber v2](https://github.com/gofiber/fiber/v2)
- **Database**: GORM with support for PostgreSQL and MySQL
- **Authentication**: JWT-based auth with access/refresh token rotation
- **Architecture**: Clean Architecture with Generic Base Repository
- **Logging**: Structured logging with Uber Zap
- **Configuration**: Environment variable management with SPF13 Viper
- **Validation**: Request validation using Go Playground Validator v10
- **Security**: Soft deletes, Bcrypt password hashing, and CORS support
- **Lifecycle**: Graceful shutdown and signal handling

## Project Structure

```text
go-fiber-template/
├── cmd/
│   └── server/
│       └── main.go              # Entry point + Manual DI wiring
├── internal/
│   └── app/
│       ├── entity/              # GORM models
│       ├── dto/                 # Data Transfer Objects
│       ├── repository/          # Repository interfaces & GORM implementations
│       ├── service/             # Business logic
│       ├── handler/             # Fiber HTTP handlers
│       └── middleware/          # Security, RBAC, Logging, Error handling
├── pkg/
│   ├── response/                # Standardized JSON response format
│   ├── utils/                   # Hash, JWT, Pagination helpers
│   └── database/                # Database connection logic
├── config/                      # Configuration loader
├── .env.example
├── go.mod
└── README.md
```

## Getting Started

### Prerequisites

- Go 1.22+
- PostgreSQL or MySQL
- Make (optional)

### Installation

1. Clone the repository
2. Copy `.env.example` to `.env` and update the database credentials:
   ```bash
   cp .env.example .env
   ```
3. Install dependencies:
   ```bash
   go mod download
   ```
4. Run the server:
   ```bash
   go run cmd/server/main.go
   ```

## API Endpoints

### Auth
- `POST /api/v1/auth/register` - Create a new user
- `POST /api/v1/auth/login` - Authenticate and get tokens
- `POST /api/v1/auth/refresh` - Rotate refresh token
- `POST /api/v1/auth/logout` - Revoke refresh token

### Users
- `GET /api/v1/users/me` - Authenticated user profile
- `GET /api/v1/users/:id` - Get user by ID (Self or Admin)
- `PUT /api/v1/users/:id` - Update user profile
- `PUT /api/v1/users/:id/password` - Change account password

### Admin
- `GET /api/v1/admin/users` - List all users (Paginated + Filter)
- `DELETE /api/v1/admin/users/:id` - Soft delete user
- `PATCH /api/v1/admin/users/:id/activate` - Re-activate account
- `PATCH /api/v1/admin/users/:id/deactivate` - Deactivate account

## Quality Constraints

- Every exported function has a Go doc comment
- Context-aware database operations
- Manual Dependency Injection
- Standardized API contracts
- RBAC (Role-Based Access Control)
```
