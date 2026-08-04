package handler

import (
	"encoding/json"
	"log"

	"go-fiber-template/internal/service"

	"github.com/gofiber/contrib/websocket"
	"github.com/gofiber/fiber/v2"
)

type WSHandler struct {
	hub              *WSHub
	configService    service.AsvConfigService
	pidConfigService service.PidConfigService
}

func NewWSHandler(hub *WSHub, configService service.AsvConfigService, pidConfigService service.PidConfigService) *WSHandler {
	return &WSHandler{
		hub:              hub,
		configService:    configService,
		pidConfigService: pidConfigService,
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

	// Broadcast ke Web UI bahwa ASV sudah terhubung
	h.hub.BroadcastWarningToWeb("info", "ASV_CONNECTED", "Mini PC (ASV) berhasil terhubung ke base station")

	defer func() {
		h.hub.Unregister(client)
		// Broadcast ke semua Web UI bahwa ASV/Mini PC terputus
		h.hub.BroadcastWarningToWeb(
			"critical",
			"ASV_DISCONNECTED",
			"⚠️ KRITIS: Koneksi Mini PC ke Base Station terputus! Komunikasi dengan Flight Controller hilang.",
		)
		log.Println("[WSHandler] ASV disconnected — warning broadcast sent to all Web clients")
	}()

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

	// Send initial PID config from DB to ASV
	if pidCfg, err := h.pidConfigService.GetConfig(); err == nil && pidCfg != nil {
		initialPidCmd := map[string]interface{}{
			"type": "COMMAND",
			"cmd": map[string]interface{}{
				"action":             "update_pid",
				"kp":                 pidCfg.Kp,
				"ki":                 pidCfg.Ki,
				"kd":                 pidCfg.Kd,
				"forward_speed":      pidCfg.ForwardSpeed,
				"align_threshold_px": pidCfg.AlignThresholdPx,
			},
		}
		if cmdBytes, err := json.Marshal(initialPidCmd); err == nil {
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
				msgType, _ := payload["type"].(string)

				switch msgType {
				case "CHANNEL_CONFIG":
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

				case "WARNING":
					// ASV mengirim warning (misal: sensor error, FC disconnect) → forward ke Web
					log.Printf("[WSHandler] WARNING dari ASV: %s", string(msg))
					h.hub.BroadcastToWeb(msg)
					continue // sudah di-forward, skip broadcast normal

				case "FC_DISCONNECTED":
					// Mini PC terputus dari Flight Controller
					h.hub.BroadcastWarningToWeb(
						"critical",
						"FC_DISCONNECTED",
						"⚠️ KRITIS: Mini PC terputus dari Flight Controller! Kapal tidak dapat dikontrol.",
					)
					log.Println("[WSHandler] FC_DISCONNECTED event received from ASV")
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

	// Jika saat ini tidak ada ASV terhubung, beri tahu Web client ini
	if !h.hub.HasASVClient() {
		h.hub.BroadcastWarningToWeb(
			"warning",
			"ASV_OFFLINE",
			"Mini PC (ASV) belum terhubung ke base station",
		)
	}

	for {
		mt, msg, err := c.ReadMessage()
		if err != nil {
			log.Printf("Web read error: %v", err)
			break
		}
		if mt == websocket.TextMessage {
			// Intercept update_pid to persist in Database
			var payload map[string]interface{}
			if err := json.Unmarshal(msg, &payload); err == nil {
				if msgType, ok := payload["type"].(string); ok && msgType == "COMMAND" {
					if cmd, ok := payload["cmd"].(map[string]interface{}); ok {
						if action, ok := cmd["action"].(string); ok && action == "update_pid" {
							if pidCfg, err := h.pidConfigService.GetConfig(); err == nil && pidCfg != nil {
								if val, ok := cmd["kp"].(float64); ok {
									pidCfg.Kp = val
								}
								if val, ok := cmd["ki"].(float64); ok {
									pidCfg.Ki = val
								}
								if val, ok := cmd["kd"].(float64); ok {
									pidCfg.Kd = val
								}
								if val, ok := cmd["forward_speed"].(float64); ok {
									pidCfg.ForwardSpeed = val
								}
								if val, ok := cmd["align_threshold_px"].(float64); ok {
									pidCfg.AlignThresholdPx = val
								}
								h.pidConfigService.SaveConfig(pidCfg)
								log.Println("[WSHandler] Saved updated PID config to Database")
							}
						}
					}
				}
			}
			// Broadcast commands from Web UI to ASV
			h.hub.BroadcastToASV(msg)
		}
	}
}


