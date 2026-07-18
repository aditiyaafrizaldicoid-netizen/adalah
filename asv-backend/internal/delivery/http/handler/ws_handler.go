package handler

import (
	"encoding/json"
	"log"

	"go-fiber-template/internal/service"

	"github.com/gofiber/contrib/websocket"
	"github.com/gofiber/fiber/v2"
)

type WSHandler struct {
	hub           *WSHub
	configService service.AsvConfigService
}

func NewWSHandler(hub *WSHub, configService service.AsvConfigService) *WSHandler {
	return &WSHandler{
		hub:           hub,
		configService: configService,
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

	// Send initial config from DB
	if config, err := h.configService.GetConfig(); err == nil && config != nil {
		initialCmd := map[string]interface{}{
			"type": "COMMAND",
			"cmd": map[string]interface{}{
				"action": "set_channel_map",
				"channel_map": map[string]interface{}{
					"thruster_left_ch":  config.ThrusterLeftCh,
					"thruster_right_ch": config.ThrusterRightCh,
					"servo_left_ch":     config.ServoLeftCh,
					"servo_right_ch":    config.ServoRightCh,
					"servo_method":      config.ServoMethod,
				},
			},
		}
		if cmdBytes, err := json.Marshal(initialCmd); err == nil {
			c.WriteMessage(websocket.TextMessage, cmdBytes)
		}
	}

	for {
		mt, msg, err := c.ReadMessage()
		if err != nil {
			log.Printf("ASV read error: %v", err)
			break
		}
		if mt == websocket.TextMessage {
			// Intercept CHANNEL_CONFIG to save to DB
			var payload map[string]interface{}
			if err := json.Unmarshal(msg, &payload); err == nil {
				if payload["type"] == "CHANNEL_CONFIG" {
					if data, ok := payload["payload"].(map[string]interface{}); ok {
						if config, err := h.configService.GetConfig(); err == nil && config != nil {
							if val, ok := data["thruster_left_ch"].(float64); ok {
								config.ThrusterLeftCh = int(val)
							}
							if val, ok := data["thruster_right_ch"].(float64); ok {
								config.ThrusterRightCh = int(val)
							}
							if val, ok := data["servo_left_ch"].(float64); ok {
								config.ServoLeftCh = int(val)
							}
							if val, ok := data["servo_right_ch"].(float64); ok {
								config.ServoRightCh = int(val)
							}
							if val, ok := data["servo_method"].(string); ok {
								config.ServoMethod = val
							}
							h.configService.UpdateConfig(config)
						}
					}
				}
			}

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
