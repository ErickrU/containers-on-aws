// shopfront/catalog: the products API with a Valkey cache-aside in front of PostgreSQL.
//
// Lifecycle (labs/CONTRACT.md §7): validate config -> connect to the database with backoff (30 s)
// -> start HTTP -> serve. On SIGTERM/SIGINT: stop accepting connections, finish in-flight requests,
// flush traces, close the cache and the pool, exit 0, all within SHUTDOWN_TIMEOUT_SECONDS.
// Exit codes: 0 clean, 1 runtime error, 2 configuration error.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/cache"
	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/config"
	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/httpapi"
	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/store"
	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/telemetry"
)

const (
	exitOK          = 0
	exitRuntime     = 1
	exitConfigError = 2

	databaseConnectWait = 30 * time.Second
)

// version is set at build time: -ldflags "-X main.version=<tag or sha>".
var version = "dev"

func main() { os.Exit(run()) }

func run() int {
	cfg, err := config.Load(os.LookupEnv)
	if err != nil {
		fmt.Fprintf(os.Stderr, "configuration error: %v\n", err)
		return exitConfigError
	}

	logger := telemetry.NewLogger(os.Stdout, cfg.LogLevel, cfg.ServiceName)
	slog.SetDefault(logger)
	logger.Info("starting catalog",
		"version", version,
		"port", cfg.Port,
		"database_url", cfg.RedactedDatabaseURL(),
		"valkey_url", cfg.RedactedValkeyURL(),
		"cache_ttl_seconds", cfg.CacheTTL.Seconds(),
		"shutdown_timeout_seconds", cfg.ShutdownTimeout.Seconds(),
	)

	// ctx is cancelled by SIGTERM (platform stop) or SIGINT (Ctrl-C); every start-up step honours it.
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()

	flushTraces, err := telemetry.SetupTracing(ctx, cfg.ServiceName, cfg.OTLPEndpoint, logger)
	if err != nil {
		logger.Error("tracing setup failed", "error", err.Error())
		return exitRuntime
	}

	db, err := store.Connect(ctx, cfg.DatabaseURL, databaseConnectWait, logger)
	if err != nil {
		logger.Error("giving up on the database", "error", err.Error())
		return exitRuntime
	}

	var productCache cache.Cache = cache.Disabled{}
	readyChecks := map[string]httpapi.ReadyCheck{"database": db.Ping}
	if cfg.ValkeyURL == "" {
		logger.Info("cache disabled: VALKEY_URL is not set, X-Cache will be BYPASS")
	} else {
		valkey, err := cache.NewValkey(cfg.ValkeyURL)
		if err != nil {
			fmt.Fprintf(os.Stderr, "configuration error: %v\n", err)
			db.Close()
			return exitConfigError
		}
		productCache = valkey
		readyChecks["cache"] = valkey.Ping
	}

	api := httpapi.New(httpapi.Deps{
		Store:       db,
		Cache:       productCache,
		CacheTTL:    cfg.CacheTTL,
		Metrics:     telemetry.NewMetrics(),
		Logger:      logger,
		ReadyChecks: readyChecks,
	})
	server := &http.Server{
		Addr:              fmt.Sprintf(":%d", cfg.Port),
		Handler:           api,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       15 * time.Second,
		WriteTimeout:      30 * time.Second,
		IdleTimeout:       60 * time.Second,
	}

	serverErr := make(chan error, 1)
	go func() {
		logger.Info("listening", "addr", server.Addr)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			serverErr <- err
		}
	}()

	exitCode := exitOK
	select {
	case err := <-serverErr:
		logger.Error("http server failed", "error", err.Error())
		exitCode = exitRuntime
	case <-ctx.Done():
		logger.Info("shutdown signal received", "timeout_seconds", cfg.ShutdownTimeout.Seconds())
	}
	stop()

	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Warn("http server did not drain in time", "error", err.Error())
	}
	if err := flushTraces(shutdownCtx); err != nil {
		logger.Warn("trace flush incomplete", "error", err.Error())
	}
	if err := productCache.Close(); err != nil {
		logger.Warn("cache close failed", "error", err.Error())
	}
	db.Close()
	logger.Info("catalog stopped", "exit_code", exitCode)
	return exitCode
}
