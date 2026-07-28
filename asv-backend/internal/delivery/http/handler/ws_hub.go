package handler

import (
	"encoding/json"
	"log"
	"sync"
	"time"

	"github.com/gofiber/contrib/websocket"
)

type ClientType string

const (
	ClientTypeASV ClientType = "ASV"
	ClientTypeWeb ClientType = "WEB"
)

type Client struct {
	Conn *websocket.Conn
	Type ClientType
}

type WSHub struct {
	clients map[*Client]bool
	mu      sync.Mutex
}

func NewWSHub() *WSHub {
	return &WSHub{
		clients: make(map[*Client]bool),
	}
}

func (h *WSHub) Register(c *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[c] = true
	log.Printf("Client registered: %s", c.Type)
}

func (h *WSHub) Unregister(c *Client) {
	h.mu.Lock()
	defer h.mu.Unlock()
	if _, ok := h.clients[c]; ok {
		delete(h.clients, c)
		c.Conn.Close()
		log.Printf("Client unregistered: %s", c.Type)
	}
}

func (h *WSHub) BroadcastToWeb(message []byte) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for c := range h.clients {
		if c.Type == ClientTypeWeb {
			if err := c.Conn.WriteMessage(websocket.TextMessage, message); err != nil {
				log.Printf("Error writing to Web client: %v", err)
				c.Conn.Close()
				delete(h.clients, c)
			}
		}
	}
}

func (h *WSHub) BroadcastToASV(message []byte) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for c := range h.clients {
		if c.Type == ClientTypeASV {
			if err := c.Conn.WriteMessage(websocket.TextMessage, message); err != nil {
				log.Printf("Error writing to ASV client: %v", err)
				c.Conn.Close()
				delete(h.clients, c)
			}
		}
	}
}

// BroadcastWarningToWeb mengirim pesan WARNING JSON ke semua Web UI client.
// level: "critical" | "warning" | "info"
func (h *WSHub) BroadcastWarningToWeb(level, code, message string) {
	payload := map[string]interface{}{
		"type": "WARNING",
		"payload": map[string]interface{}{
			"level":     level,
			"code":      code,
			"message":   message,
			"timestamp": time.Now().UnixMilli(),
		},
	}
	data, err := json.Marshal(payload)
	if err != nil {
		log.Printf("Error marshaling warning: %v", err)
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	for c := range h.clients {
		if c.Type == ClientTypeWeb {
			if err := c.Conn.WriteMessage(websocket.TextMessage, data); err != nil {
				log.Printf("Error sending warning to Web client: %v", err)
				c.Conn.Close()
				delete(h.clients, c)
			}
		}
	}
}

// HasASVClient mengembalikan true jika setidaknya ada 1 ASV yang terhubung.
func (h *WSHub) HasASVClient() bool {
	h.mu.Lock()
	defer h.mu.Unlock()
	for c := range h.clients {
		if c.Type == ClientTypeASV {
			return true
		}
	}
	return false
}
