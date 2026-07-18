package entity

import "time"

type AsvConfig struct {
	ID              uint      `gorm:"primaryKey"`
	ThrusterLeftCh  int       `gorm:"default:1"`
	ThrusterRightCh int       `gorm:"default:3"`
	ServoLeftCh     int       `gorm:"default:2"`
	ServoRightCh    int       `gorm:"default:4"`
	ServoMethod     string    `gorm:"default:'rc_override'"`
	UpdatedAt       time.Time `gorm:"autoUpdateTime"`
}
