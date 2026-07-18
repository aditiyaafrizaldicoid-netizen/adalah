package utils

import (
	"strconv"

	"github.com/gofiber/fiber/v2"
)

type Pagination struct {
	Limit  int    `json:"limit"`
	Page   int    `json:"page"`
	Sort   string `json:"sort"`
	SortBy string `json:"sort_by"`
	Search string `json:"search"`
}

func GeneratePaginationFromRequest(c *fiber.Ctx) *Pagination {
	limit := 10
	page := 1
	sort := "desc"
	sortBy := "created_at"

	if limitStr := c.Query("limit"); limitStr != "" {
		if l, err := strconv.Atoi(limitStr); err == nil && l > 0 {
			limit = l
		}
	}

	if pageStr := c.Query("page"); pageStr != "" {
		if p, err := strconv.Atoi(pageStr); err == nil && p > 0 {
			page = p
		}
	}

	if sortStr := c.Query("sort"); sortStr == "asc" || sortStr == "desc" {
		sort = sortStr
	}

	if sortByStr := c.Query("sort_by"); sortByStr != "" {
		sortBy = sortByStr
	}

	search := c.Query("search")

	return &Pagination{
		Limit:  limit,
		Page:   page,
		Sort:   sort,
		SortBy: sortBy,
		Search: search,
	}
}

func (p *Pagination) GetOffset() int {
	return (p.Page - 1) * p.Limit
}
