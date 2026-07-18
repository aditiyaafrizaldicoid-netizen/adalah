package handler

import (
	"log"

	"github.com/gofiber/contrib/websocket"
	"github.com/gofiber/fiber/v2"
)

type WSHandler struct {
	hub *WSHub
}

func NewWSHandler(hub *WSHub) *WSHandler {
	return &WSHandler{
		hub: hub,
	}
}

// Upgrade middleware
func (h *WSHandler) Upgrade(c *fiber.Ctx) error {
	if websocket.IsWebSocketUpgrade(c) {
		c.Locals("allowed", true)
		return c.Next()
	}
	return fiber.ErrUpgradeRequired
}

// Handle ASV connection
func (h *WSHandler) HandleASV(c *websocket.Conn) {
	client := &Client{Conn: c, Type: ClientTypeASV}
	h.hub.Register(client)
	defer h.hub.Unregister(client)

	for {
		mt, msg, err := c.ReadMessage()
		if err != nil {
			log.Printf("ASV read error: %v", err)
			break
		}
		if mt == websocket.TextMessage {
			// Broadcast telemetry from ASV to Web UI
			h.hub.BroadcastToWeb(msg)
		}
	}
}

// Handle Web UI connection
func (h *WSHandler) HandleWeb(c *websocket.Conn) {
	client := &Client{Conn: c, Type: ClientTypeWeb}
	h.hub.Register(client)
	defer h.hub.Unregister(client)

	for {
		mt, msg, err := c.ReadMessage()
		if err != nil {
			log.Printf("Web read error: %v", err)
			break
		}
		if mt == websocket.TextMessage {
			// Broadcast commands from Web UI to ASV
			h.hub.BroadcastToASV(msg)
		}
	}
}
