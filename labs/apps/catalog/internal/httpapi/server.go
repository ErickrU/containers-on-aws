// Package httpapi is the HTTP surface of the catalog service (labs/CONTRACT.md §3).
package httpapi

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
	"go.opentelemetry.io/otel/trace"

	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/cache"
	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/store"
	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/telemetry"
)

// ReadyCheck is one dependency probe run by GET /readyz; nil means "ok".
type ReadyCheck func(ctx context.Context) error

// Deps is everything the server needs. main wires the real implementations, tests use fakes.
type Deps struct {
	Store    store.Store
	Cache    cache.Cache
	CacheTTL time.Duration
	Metrics  *telemetry.Metrics
	Logger   *slog.Logger
	// ReadyChecks are reported by name in the /readyz body: {"database": "ok", "cache": "ok"}.
	ReadyChecks map[string]ReadyCheck
}

// Server is an http.Handler: otelhttp (server span, W3C context extraction) wraps the metrics and
// request-log middleware, which wraps the method-and-pattern router.
type Server struct {
	store       store.Store
	cache       cache.Cache
	cacheTTL    time.Duration
	metrics     *telemetry.Metrics
	logger      *slog.Logger
	readyChecks map[string]ReadyCheck
	handler     http.Handler
}

// New builds the router and middleware chain.
func New(d Deps) *Server {
	s := &Server{
		store:       d.Store,
		cache:       d.Cache,
		cacheTTL:    d.CacheTTL,
		metrics:     d.Metrics,
		logger:      d.Logger,
		readyChecks: d.ReadyChecks,
	}
	if s.logger == nil {
		s.logger = slog.Default()
	}
	if s.metrics == nil {
		s.metrics = telemetry.NewMetrics()
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", s.handleHealthz)
	mux.HandleFunc("GET /readyz", s.handleReadyz)
	mux.Handle("GET /metrics", s.metrics.Handler())
	mux.HandleFunc("GET /products", s.handleListProducts)
	mux.HandleFunc("GET /products/{id}", s.handleGetProduct)
	mux.HandleFunc("/", s.handleNotFound)

	// Probes and scrapes are not traced: they would dominate the trace volume with no value.
	// otelhttp names the span with the formatter twice: at the start (no pattern known yet, so the
	// operation name) and again after routing, when r.Pattern is set: "GET /products/{id}".
	s.handler = otelhttp.NewHandler(s.instrument(mux), "catalog",
		otelhttp.WithFilter(func(r *http.Request) bool { return !isProbe(r.URL.Path) }),
		otelhttp.WithSpanNameFormatter(func(operation string, r *http.Request) string {
			if r.Pattern == "" {
				return operation
			}
			return r.Method + " " + routeLabel(r.Pattern)
		}),
	)
	return s
}

// ServeHTTP makes Server usable directly by http.Server and by httptest.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) { s.handler.ServeHTTP(w, r) }

// instrument records http_requests_total and http_request_duration_seconds with the matched route
// pattern as label (bounded cardinality), sets http.route on the server span and writes one
// request log line.
func (s *Server) instrument(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rw := &statusWriter{ResponseWriter: w, status: http.StatusOK}

		next.ServeHTTP(rw, r)

		// ServeMux fills r.Pattern on this very request once it has picked a handler (Go 1.23).
		route := routeLabel(r.Pattern)
		elapsed := time.Since(start)
		status := strconv.Itoa(rw.status)
		s.metrics.HTTPRequests.WithLabelValues(r.Method, route, status).Inc()
		s.metrics.HTTPDuration.WithLabelValues(r.Method, route).Observe(elapsed.Seconds())

		if span := trace.SpanFromContext(r.Context()); span.IsRecording() {
			span.SetAttributes(semconv.HTTPRoute(route))
		}

		level := slog.LevelInfo
		if isProbe(r.URL.Path) {
			level = slog.LevelDebug // liveness/readiness/scrapes would flood the log at info
		}
		s.logger.Log(r.Context(), level, "http request",
			"method", r.Method,
			"route", route,
			"path", r.URL.Path,
			"status", rw.status,
			"duration_ms", float64(elapsed.Microseconds())/1000,
		)
	})
}

func isProbe(path string) bool {
	return path == "/healthz" || path == "/readyz" || path == "/metrics"
}

// routeLabel turns "GET /products/{id}" into "/products/{id}"; unmatched requests share one label.
func routeLabel(pattern string) string {
	if pattern == "" || pattern == "/" {
		return "unknown"
	}
	if i := strings.IndexByte(pattern, ' '); i >= 0 {
		return pattern[i+1:]
	}
	return pattern
}

// statusWriter remembers the status code for metrics and logs.
type statusWriter struct {
	http.ResponseWriter
	status      int
	wroteHeader bool
}

func (w *statusWriter) WriteHeader(code int) {
	if !w.wroteHeader {
		w.status = code
		w.wroteHeader = true
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *statusWriter) Write(b []byte) (int, error) {
	if !w.wroteHeader {
		w.wroteHeader = true // implicit 200
	}
	return w.ResponseWriter.Write(b)
}

// Unwrap lets http.ResponseController reach the underlying writer (flushing, deadlines).
func (w *statusWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

func writeJSON(w http.ResponseWriter, status int, v any) {
	body, err := json.Marshal(v)
	if err != nil {
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}
	writeRawJSON(w, status, body)
}

func writeRawJSON(w http.ResponseWriter, status int, body []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
