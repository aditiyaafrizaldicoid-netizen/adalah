package config

import (
	"os"

	"go.uber.org/zap"
	"go.uber.org/zap/zapcore"
)

// NewLogger initializes a multi-level zap logger.
func NewLogger(cfg *Config) *zap.Logger {
	if cfg.App.Env != "production" {
		config := zap.NewDevelopmentConfig()
		config.EncoderConfig.EncodeLevel = zapcore.CapitalColorLevelEncoder
		config.OutputPaths = []string{"stdout"}
		config.ErrorOutputPaths = []string{"stderr"}

		logger, _ := config.Build(zap.AddStacktrace(zapcore.ErrorLevel))
		return logger
	}

	// Production Logging - Separate files by level
	encoderConfig := zap.NewProductionEncoderConfig()
	encoderConfig.EncodeTime = zapcore.ISO8601TimeEncoder
	encoder := zapcore.NewJSONEncoder(encoderConfig)

	// Ensure logs directory exists
	if err := os.MkdirAll("logs", 0755); err != nil {
		panic(err)
	}

	// Open log files
	infoFile, _ := os.OpenFile("logs/info.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	warnFile, _ := os.OpenFile("logs/warn.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	errorFile, _ := os.OpenFile("logs/error.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)

	// Define level filters
	infoLevel := zap.LevelEnablerFunc(func(l zapcore.Level) bool {
		return l == zapcore.InfoLevel
	})
	warnLevel := zap.LevelEnablerFunc(func(l zapcore.Level) bool {
		return l == zapcore.WarnLevel
	})
	errorLevel := zap.LevelEnablerFunc(func(l zapcore.Level) bool {
		return l >= zapcore.ErrorLevel
	})

	// Create core with multi-sink
	core := zapcore.NewTee(
		zapcore.NewCore(encoder, zapcore.AddSync(infoFile), infoLevel),
		zapcore.NewCore(encoder, zapcore.AddSync(warnFile), warnLevel),
		zapcore.NewCore(encoder, zapcore.AddSync(errorFile), errorLevel),
		// Also output to stdout in production but as JSON
		zapcore.NewCore(encoder, zapcore.AddSync(os.Stdout), zapcore.InfoLevel),
	)

	return zap.New(core, zap.AddCaller(), zap.AddStacktrace(zapcore.ErrorLevel))
}
