// Package config reads the catalog configuration from the environment (labs/CONTRACT.md §2).
//
// Twelve-factor: the environment is the only source. Unknown variables are ignored; a missing or
// malformed required variable is reported with a clear message and the process exits with code 2.
package config

import (
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const (
	DefaultPort            = 8081
	DefaultCacheTTL        = 60 * time.Second
	DefaultShutdownTimeout = 20 * time.Second
	DefaultServiceName     = "catalog"
)

// Config is the fully resolved configuration of one catalog process.
type Config struct {
	Port        int
	DatabaseURL string
	// ValkeyURL is empty when VALKEY_URL is unset: the service then runs without a cache and
	// answers X-Cache: BYPASS.
	ValkeyURL string
	CacheTTL  time.Duration
	// OTLPEndpoint is empty when OTEL_EXPORTER_OTLP_ENDPOINT is unset: tracing is disabled.
	OTLPEndpoint    string
	ServiceName     string
	LogLevel        slog.Level
	ShutdownTimeout time.Duration
}

// Lookup mirrors os.LookupEnv so tests can inject an environment.
type Lookup func(key string) (string, bool)

// Load resolves the configuration. All problems are reported together so an operator fixes the
// task definition or manifest once instead of once per variable.
func Load(lookup Lookup) (Config, error) {
	cfg := Config{
		Port:            DefaultPort,
		CacheTTL:        DefaultCacheTTL,
		ServiceName:     DefaultServiceName,
		LogLevel:        slog.LevelInfo,
		ShutdownTimeout: DefaultShutdownTimeout,
	}
	var errs []error

	if v, ok := value(lookup, "DATABASE_URL"); ok {
		cfg.DatabaseURL = v
	} else {
		errs = append(errs, errors.New("DATABASE_URL is required, for example postgres://app:app@postgres:5432/shopfront"))
	}

	cfg.ValkeyURL, _ = value(lookup, "VALKEY_URL")
	cfg.OTLPEndpoint, _ = value(lookup, "OTEL_EXPORTER_OTLP_ENDPOINT")
	if v, ok := value(lookup, "OTEL_SERVICE_NAME"); ok {
		cfg.ServiceName = v
	}

	if v, ok := value(lookup, "PORT"); ok {
		port, err := strconv.Atoi(v)
		if err != nil || port < 1 || port > 65535 {
			errs = append(errs, fmt.Errorf("PORT must be an integer between 1 and 65535, got %q", v))
		} else {
			cfg.Port = port
		}
	}

	if v, ok := value(lookup, "CACHE_TTL_SECONDS"); ok {
		d, err := seconds(v)
		if err != nil {
			errs = append(errs, fmt.Errorf("CACHE_TTL_SECONDS: %w", err))
		} else {
			cfg.CacheTTL = d
		}
	}

	if v, ok := value(lookup, "SHUTDOWN_TIMEOUT_SECONDS"); ok {
		d, err := seconds(v)
		if err != nil {
			errs = append(errs, fmt.Errorf("SHUTDOWN_TIMEOUT_SECONDS: %w", err))
		} else {
			cfg.ShutdownTimeout = d
		}
	}

	if v, ok := value(lookup, "LOG_LEVEL"); ok {
		level, err := parseLevel(v)
		if err != nil {
			errs = append(errs, err)
		} else {
			cfg.LogLevel = level
		}
	}

	return cfg, errors.Join(errs...)
}

// RedactedDatabaseURL is safe to log: the password is replaced.
func (c Config) RedactedDatabaseURL() string { return redactURL(c.DatabaseURL) }

// RedactedValkeyURL is safe to log: the password, if any, is replaced.
func (c Config) RedactedValkeyURL() string { return redactURL(c.ValkeyURL) }

func value(lookup Lookup, key string) (string, bool) {
	v, ok := lookup(key)
	v = strings.TrimSpace(v)
	return v, ok && v != ""
}

func seconds(raw string) (time.Duration, error) {
	n, err := strconv.Atoi(raw)
	if err != nil || n < 1 {
		return 0, fmt.Errorf("must be a positive integer number of seconds, got %q", raw)
	}
	return time.Duration(n) * time.Second, nil
}

func parseLevel(raw string) (slog.Level, error) {
	switch strings.ToLower(raw) {
	case "debug":
		return slog.LevelDebug, nil
	case "info":
		return slog.LevelInfo, nil
	case "warn", "warning":
		return slog.LevelWarn, nil
	case "error":
		return slog.LevelError, nil
	}
	return 0, fmt.Errorf("LOG_LEVEL must be one of debug, info, warn, error, got %q", raw)
}

func redactURL(raw string) string {
	if raw == "" {
		return ""
	}
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		// key=value connection strings and anything unparsable: hide everything rather than risk a leak
		return "<redacted>"
	}
	return u.Redacted()
}
