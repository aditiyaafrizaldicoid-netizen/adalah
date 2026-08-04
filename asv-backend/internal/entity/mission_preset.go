package entity

import "time"

type MissionPreset struct {
	ID        uint      `gorm:"primaryKey" json:"id"`
	Name      string    `gorm:"size:255;not null" json:"name"`
	Steps     string    `gorm:"type:text;not null" json:"steps"` // JSON string array of steps
	CreatedAt time.Time `json:"created_at"`
	UpdatedAt time.Time `json:"updated_at"`
}
