.PHONY: run migrate seed build mod-tidy test test-coverage docs

run:
	go run cmd/server/main.go

migrate:
	go run cmd/migrate/main.go

seed:
	go run cmd/seed/main.go

refresh:
	go run cmd/refresh/main.go

test:
	go test -v ./...

test-coverage:
	go test -coverprofile=coverage.out ./...
	go tool cover -html=coverage.out

docs:
	swag init -g cmd/server/main.go -o ./docs

build:
	go build -o tmp/main cmd/server/main.go

mod-tidy:
	go get github.com/gofiber/fiber/v2
	go mod tidy
