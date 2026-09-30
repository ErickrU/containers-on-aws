package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/trace"

	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/cache"
	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/store"
)

// X-Cache values (labs/CONTRACT.md §3).
const (
	cacheHit    = "HIT"    // answered from Valkey
	cacheMiss   = "MISS"   // read from PostgreSQL, then written to Valkey
	cacheBypass = "BYPASS" // no cache configured, or the cache did not answer
)

const readyCheckTimeout = 2 * time.Second

type readyResponse struct {
	Status string            `json:"status"`
	Checks map[string]string `json:"checks"`
}

// GET /healthz: liveness. The process is up and its event loop answers; nothing else is checked.
func (s *Server) handleHealthz(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// GET /readyz: readiness. Every dependency check is run and reported by name; one failure means
// 503, which tells the load balancer to stop routing here without restarting the task.
func (s *Server) handleReadyz(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), readyCheckTimeout)
	defer cancel()

	resp := readyResponse{Status: "ready", Checks: make(map[string]string, len(s.readyChecks))}
	status := http.StatusOK
	for name, check := range s.readyChecks {
		if err := check(ctx); err != nil {
			resp.Checks[name] = "error: " + err.Error()
			resp.Status = "not-ready"
			status = http.StatusServiceUnavailable
			s.logger.WarnContext(ctx, "readiness check failed", "check", name, "error", err.Error())
			continue
		}
		resp.Checks[name] = "ok"
	}
	writeJSON(w, status, resp)
}

// GET /products: the whole list from PostgreSQL, never cached.
func (s *Server) handleListProducts(w http.ResponseWriter, r *http.Request) {
	products, err := s.store.ListProducts(r.Context())
	if err != nil {
		s.logger.ErrorContext(r.Context(), "list products failed", "error", err.Error())
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if products == nil {
		products = []store.Product{}
	}
	writeJSON(w, http.StatusOK, products)
}

// GET /products/{id}: cache-aside. Look in Valkey first; on a miss read PostgreSQL and fill the
// cache with the same JSON that is sent to the client. Cache failures degrade to BYPASS.
func (s *Server) handleGetProduct(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	id, err := strconv.ParseInt(r.PathValue("id"), 10, 64)
	if err != nil || id < 1 {
		writeError(w, http.StatusBadRequest, "product id must be a positive integer")
		return
	}
	key := "product:" + strconv.FormatInt(id, 10)

	state := cacheMiss
	cached, err := s.cache.Get(ctx, key)
	switch {
	case err == nil && cached != nil:
		s.metrics.CacheHits.Inc()
		s.annotate(ctx, cacheHit)
		w.Header().Set("X-Cache", cacheHit)
		writeRawJSON(w, http.StatusOK, cached)
		return
	case err != nil:
		state = cacheBypass
		if !errors.Is(err, cache.ErrDisabled) {
			s.logger.WarnContext(ctx, "cache unavailable, reading from database", "error", err.Error())
		}
	}

	product, err := s.store.GetProduct(ctx, id)
	if errors.Is(err, store.ErrNotFound) {
		s.annotate(ctx, state)
		writeError(w, http.StatusNotFound, "not found")
		return
	}
	if err != nil {
		s.logger.ErrorContext(ctx, "get product failed", "product_id", id, "error", err.Error())
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	body, err := json.Marshal(product)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if state == cacheMiss {
		s.metrics.CacheMisses.Inc()
		if err := s.cache.Set(ctx, key, body, s.cacheTTL); err != nil {
			s.logger.WarnContext(ctx, "cache fill failed", "key", key, "error", err.Error())
		}
	}
	s.annotate(ctx, state)
	w.Header().Set("X-Cache", state)
	writeRawJSON(w, http.StatusOK, body)
}

func (s *Server) handleNotFound(w http.ResponseWriter, _ *http.Request) {
	writeError(w, http.StatusNotFound, "not found")
}

// annotate records the cache outcome on the server span so a trace shows HIT/MISS/BYPASS.
func (s *Server) annotate(ctx context.Context, state string) {
	if span := trace.SpanFromContext(ctx); span.IsRecording() {
		span.SetAttributes(attribute.String("shopfront.cache", state))
	}
}
