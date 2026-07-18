package handler

import (
	"log"
	"sync"

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
