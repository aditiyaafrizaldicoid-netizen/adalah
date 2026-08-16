package entity

import "time"

// Arena menyimpan konfigurasi lapangan kompetisi ASV.
// Buoys dan Trails disimpan sebagai JSON string (array of objects).
type Arena struct {
	ID          uint      `gorm:"primaryKey" json:"id"`
	Name        string    `gorm:"size:255;not null" json:"name"`
	Description string    `gorm:"size:500" json:"description"`
	Buoys       string    `gorm:"type:text;not null;default:'[]'" json:"buoys"`   // JSON: [{id,type,lat,lng,label}]
	Trails      string    `gorm:"type:text;not null;default:'[]'" json:"trails"`  // JSON: [{id,type,label,points:[{lat,lng}]}]
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}
