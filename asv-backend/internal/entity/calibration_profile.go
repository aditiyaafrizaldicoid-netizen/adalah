package entity

import "time"

type CalibrationProfile struct {
	ID             uint                   `gorm:"primaryKey" json:"id"`
	Name           string                 `gorm:"type:varchar(255);not null" json:"name"`
	IsDefault      bool                   `gorm:"default:false" json:"is_default"`
	ImuProfile     map[string]interface{} `gorm:"serializer:json" json:"imu_profile"`
	GpsOffset      map[string]interface{} `gorm:"serializer:json" json:"gps_offset"`
	CameraSettings map[string]interface{} `gorm:"serializer:json" json:"camera_settings"`
	ThrusterTrim   map[string]interface{} `gorm:"serializer:json" json:"thruster_trim"`
	PidTuning      map[string]interface{} `gorm:"serializer:json" json:"pid_tuning"`
	CreatedAt      time.Time              `json:"created_at"`

	UpdatedAt      time.Time              `json:"updated_at"`
}
