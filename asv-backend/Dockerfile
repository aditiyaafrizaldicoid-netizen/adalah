# ========================================================
# Stage 1: Build Environment
# ========================================================
FROM golang:1.25-alpine AS builder

# Install system build dependencies
RUN apk add --no-cache git ca-certificates tzdata build-base

WORKDIR /app

# Optimize layer caching for dependencies
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build all binaries (Server, Migrations, Seed, Refresh)
# Using -ldflags to reduce binary size
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o bin/server cmd/server/main.go && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o bin/migrate cmd/migrate/main.go && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o bin/seed cmd/seed/main.go && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o bin/refresh cmd/refresh/main.go

# ========================================================
# Stage 2: Final Runtime Image
# ========================================================
FROM alpine:3.21

# Metadata and security contact
LABEL maintainer="Darma Putra"
LABEL version="1.0"

WORKDIR /app

# Install runtime essentials
RUN apk --no-cache add ca-certificates tzdata

# Create non-root user for better security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Copy binaries from builder to a clean bin directory
COPY --from=builder /app/bin/server /app/main
COPY --from=builder /app/bin/migrate /app/migrate
COPY --from=builder /app/bin/seed /app/seed
COPY --from=builder /app/bin/refresh /app/refresh

# Set ownership to non-root user
RUN chown -R appuser:appgroup /app

# Use non-root user
USER appuser

# Document ports (Fiber default is 3000)
EXPOSE 3000

# Entry point starts the server by default
# For migrations/seeds, use: docker exec <container> ./migrate
CMD ["./main"]