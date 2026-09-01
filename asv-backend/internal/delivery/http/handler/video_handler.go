package handler

import (
	"bufio"
	"crypto/subtle"
	"io"
	"log"
	"strconv"
	"sync"
	"time"

	"go-fiber-template/internal/config"

	"github.com/gofiber/fiber/v2"
)

type VideoHandler struct {
	mu          sync.RWMutex
	latestFrame []byte
	cond        *sync.Cond
	cfg         *config.Config
}

func NewVideoHandler(cfg *config.Config) *VideoHandler {
	vh := &VideoHandler{cfg: cfg}
	vh.cond = sync.NewCond(&vh.mu)

	// Optional: Broadcast periodically so clients don't hang if no frames
	go func() {
		for {
			time.Sleep(1 * time.Second)
			vh.mu.Lock()
			vh.cond.Broadcast()
			vh.mu.Unlock()
		}
	}()

	return vh
}

// UploadFrame receives raw JPEG bytes from the Python ASV client.
//
// Dipagari kunci bersama yang sama dengan /ws/asv (ASV_WS_TOKEN): tanpa itu, siapa
// pun yang bisa menjangkau backend dapat menyuntikkan gambar ke feed yang dilihat
// operator dan juri. Kunci dikirim lewat header X-ASV-Token supaya tidak ikut
// tercatat di access log seperti query string. Kalau ASV_WS_TOKEN tidak diisi di
// server, endpoint ini tetap terbuka seperti sebelumnya — lihat AppConfig.AsvToken.
func (h *VideoHandler) UploadFrame(c *fiber.Ctx) error {
	if expected := h.cfg.App.AsvToken; expected != "" {
		got := c.Get("X-ASV-Token")
		if subtle.ConstantTimeCompare([]byte(got), []byte(expected)) != 1 {
			log.Printf("Frame upload ditolak: X-ASV-Token tidak cocok (ip=%s)", c.IP())
			return c.SendStatus(fiber.StatusUnauthorized)
		}
	}

	var frame []byte
	file, err := c.FormFile("frame")
	if err == nil {
		f, err := file.Open()
		if err == nil {
			defer f.Close()
			frame, _ = io.ReadAll(f)
		} else {
			log.Printf("Error opening file: %v", err)
			frame = c.Body()
		}
	} else {
		// Log the error to understand why it fails
		log.Printf("Error getting FormFile: %v, Content-Type: %s", err, c.Get("Content-Type"))
		frame = c.Body()
	}

	if len(frame) == 0 {
		return c.SendStatus(fiber.StatusBadRequest)
	}

	frameCopy := make([]byte, len(frame))
	copy(frameCopy, frame)

	h.mu.Lock()
	h.latestFrame = frameCopy
	h.cond.Broadcast()
	h.mu.Unlock()

	return c.SendStatus(fiber.StatusOK)
}

// StreamHandler serves an MJPEG stream to the frontend
func (h *VideoHandler) StreamHandler(c *fiber.Ctx) error {
	c.Set("Content-Type", "multipart/x-mixed-replace; boundary=frame")
	c.Set("Cache-Control", "no-cache, no-store, must-revalidate")
	c.Set("Pragma", "no-cache")
	c.Set("Expires", "0")
	c.Set("Connection", "keep-alive")
	c.Set("Access-Control-Allow-Origin", "*")

	c.Context().SetBodyStreamWriter(func(w *bufio.Writer) {
		for {
			h.mu.Lock()
			h.cond.Wait()
			frame := h.latestFrame
			h.mu.Unlock()

			if len(frame) == 0 {
				continue
			}

			header := "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + strconv.Itoa(len(frame)) + "\r\n\r\n"
			if _, err := w.Write([]byte(header)); err != nil {
				log.Println("Video stream client disconnected")
				break
			}
			if _, err := w.Write(frame); err != nil {
				log.Println("Video stream client disconnected")
				break
			}
			if _, err := w.Write([]byte("\r\n")); err != nil {
				log.Println("Video stream client disconnected")
				break
			}
			if err := w.Flush(); err != nil {
				log.Println("Video stream client disconnected")
				break
			}
		}
	})
	return nil
}
