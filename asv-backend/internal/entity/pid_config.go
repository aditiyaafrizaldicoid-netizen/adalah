package entity

import "time"

type PidConfig struct {
	ID                  uint    `gorm:"primaryKey" json:"id"`
	Kp                  float64 `gorm:"default:0.04" json:"kp"`
	Ki                  float64 `gorm:"default:0.001" json:"ki"`
	Kd                  float64 `gorm:"default:0.008" json:"kd"`
	ForwardSpeed        float64 `gorm:"default:0.4" json:"forward_speed"`
	MaxTurnRate         float64 `gorm:"default:15.0" json:"max_turn_rate"`
	AlignThresholdPx    float64 `gorm:"default:40.0" json:"align_threshold_px"`
	PassDuration        float64 `gorm:"default:2.5" json:"pass_duration"`
	CooldownDuration    float64 `gorm:"default:3.0" json:"cooldown_duration"`
	MinDetectionAreaPx2 float64 `gorm:"default:4000" json:"min_detection_area_px2"`
	// 1280x720: resolusi kerja vision & tracking.
	//
	// Mengubah resolusi WAJIB diikuti penyesuaian Kp/Ki/Kd, AlignThresholdPx, dan
	// MinDetectionAreaPx2 — semuanya berbasis PIKSEL, jadi ARTINYA ikut berubah saat
	// ukuran frame berubah. Ini bukan teori: saat resolusi sempat diturunkan ke
	// 640x360, MinDetectionAreaPx2 tertinggal di nilai lama dan seluruh bola berhenti
	// terdeteksi — bola terdekat pun hanya 784px², jauh di bawah ambang 4000.
	CameraWidth  int       `gorm:"default:1280" json:"camera_width"`
	CameraHeight int       `gorm:"default:720" json:"camera_height"`
	UpdatedAt    time.Time `gorm:"autoUpdateTime" json:"updated_at"`
}
