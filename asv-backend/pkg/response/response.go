package response

import (
	"fmt"

	ut "github.com/go-playground/universal-translator"
	"github.com/go-playground/validator/v10"
)

type PaginationMeta struct {
	Total       int64 `json:"total"`
	Limit       int   `json:"limit"`
	Page        int   `json:"page"`
	TotalPages  int   `json:"total_pages"`
	HasNext     bool  `json:"has_next"`
	HasPrevious bool  `json:"has_previous"`
}

type SuccessResponse struct {
	StatusCode int             `json:"statusCode"`
	Success    bool            `json:"success"`
	Message    string          `json:"message"`
	Data       interface{}     `json:"data"`
	Meta       *PaginationMeta `json:"meta,omitempty"`
}

type ErrorDetail struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

type ErrorResponse struct {
	Success    bool          `json:"success"`
	StatusCode int           `json:"statusCode"`
	Message    string        `json:"message"`
	Errors     []ErrorDetail `json:"errors,omitempty"`
	Stack      string        `json:"stack,omitempty"`
}

func Success(message string, statusCode int, data interface{}) SuccessResponse {
	if data == nil {
		data = map[string]interface{}{}
	}
	return SuccessResponse{
		StatusCode: statusCode,
		Success:    true,
		Message:    message,
		Data:       data,
	}
}

func Error(statusCode int, message string, errs ...ErrorDetail) ErrorResponse {
	return ErrorResponse{
		Success:    false,
		StatusCode: statusCode,
		Message:    message,
		Errors:     errs,
	}
}

func ValidationError(err error, trans ut.Translator) ErrorResponse {
	var errDetails []ErrorDetail

	if validationErrs, ok := err.(validator.ValidationErrors); ok {
		for _, e := range validationErrs {
			// Translate message automatically
			var message string
			if trans != nil {
				message = e.Translate(trans)
			} else {
				message = e.Error()
			}

			errDetails = append(errDetails, ErrorDetail{
				Field:   fmt.Sprintf("body.%s", e.Field()),
				Message: message,
			})
		}
	} else {
		errDetails = append(errDetails, ErrorDetail{
			Field:   "body",
			Message: err.Error(),
		})
	}

	return ErrorResponse{
		Success:    false,
		StatusCode: 422,
		Message:    "Validation failed",
		Errors:     errDetails,
	}
}

func SuccessWithPagination(message string, data interface{}, statusCode int, total int64, limit, page int) SuccessResponse {
	if data == nil {
		data = []interface{}{}
	}

	totalPages := 0
	if limit > 0 {
		totalPages = int((total + int64(limit) - 1) / int64(limit))
	}

	hasNext := page < totalPages
	hasPrevious := page > 1

	return SuccessResponse{
		StatusCode: statusCode,
		Success:    true,
		Message:    message,
		Data:       data,
		Meta: &PaginationMeta{
			Total:       total,
			Limit:       limit,
			Page:        page,
			TotalPages:  totalPages,
			HasNext:     hasNext,
			HasPrevious: hasPrevious,
		},
	}
}

// SwaggerSuccess is used purely for Swagger documentation to hide the meta field
type SwaggerSuccess struct {
	Success bool        `json:"success"`
	Message string      `json:"message"`
	Data    interface{} `json:"data"`
}

// SwaggerPaginated is used purely for Swagger documentation to strict the meta field
type SwaggerPaginated struct {
	Success bool           `json:"success"`
	Message string         `json:"message"`
	Data    interface{}    `json:"data"`
	Meta    PaginationMeta `json:"meta"`
}
