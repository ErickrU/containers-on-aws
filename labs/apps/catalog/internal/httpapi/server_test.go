package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/cache"
	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/store"
	"github.com/ErickrU/containers-on-aws/labs/apps/catalog/internal/telemetry"
)

// ---- fakes: no network, no database, no Valkey --------------------------------------------------

type fakeStore struct {
	products map[int64]store.Product
	pingErr  error
	getCalls int
}

func (f *fakeStore) ListProducts(context.Context) ([]store.Product, error) {
	out := make([]store.Product, 0, len(f.products))
	for _, p := range f.products {
		out = append(out, p)
	}
	return out, nil
}

func (f *fakeStore) GetProduct(_ context.Context, id int64) (store.Product, error) {
	f.getCalls++
	p, ok := f.products[id]
	if !ok {
		return store.Product{}, store.ErrNotFound
	}
	return p, nil
}

func (f *fakeStore) Ping(context.Context) error { return f.pingErr }
func (f *fakeStore) Close()                     {}

type fakeCache struct {
	data map[string][]byte
	ttl  time.Duration
}

func newFakeCache() *fakeCache { return &fakeCache{data: map[string][]byte{}} }

func (f *fakeCache) Get(_ context.Context, key string) ([]byte, error) {
	v, ok := f.data[key]
	if !ok {
		return nil, nil
	}
	return v, nil
}

func (f *fakeCache) Set(_ context.Context, key string, value []byte, ttl time.Duration) error {
	f.data[key] = value
	f.ttl = ttl
	return nil
}

func (f *fakeCache) Ping(context.Context) error { return nil }
func (f *fakeCache) Close() error               { return nil }

// ---- helpers -------------------------------------------------------------------------------------

var keyboard = store.Product{ID: 1, SKU: "KB-MECH-87", Name: "Mechanical keyboard, 87 keys", PriceCents: 8999, Stock: 120}

func newTestServer(st store.Store, c cache.Cache) *Server {
	return New(Deps{
		Store:       st,
		Cache:       c,
		CacheTTL:    45 * time.Second,
		Metrics:     telemetry.NewMetrics(),
		Logger:      slog.New(slog.NewTextHandler(io.Discard, nil)),
		ReadyChecks: map[string]ReadyCheck{"database": st.Ping, "cache": c.Ping},
	})
}

func get(t *testing.T, srv http.Handler, path string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
	return rec
}

func decode(t *testing.T, rec *httptest.ResponseRecorder, v any) {
	t.Helper()
	if ct := rec.Header().Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		t.Fatalf("Content-Type = %q, want application/json", ct)
	}
	if err := json.Unmarshal(rec.Body.Bytes(), v); err != nil {
		t.Fatalf("invalid JSON body %q: %v", rec.Body.String(), err)
	}
}

// ---- tests ---------------------------------------------------------------------------------------

func TestGetProductCacheAside(t *testing.T) {
	st := &fakeStore{products: map[int64]store.Product{1: keyboard}}
	c := newFakeCache()
	srv := newTestServer(st, c)

	first := get(t, srv, "/products/1")
	if first.Code != http.StatusOK {
		t.Fatalf("first: status = %d, want 200", first.Code)
	}
	if h := first.Header().Get("X-Cache"); h != "MISS" {
		t.Fatalf("first: X-Cache = %q, want MISS", h)
	}
	var p store.Product
	decode(t, first, &p)
	if p != keyboard {
		t.Fatalf("first: body = %+v, want %+v", p, keyboard)
	}
	if c.ttl != 45*time.Second {
		t.Fatalf("cache TTL = %s, want 45s (CACHE_TTL_SECONDS)", c.ttl)
	}
	if _, ok := c.data["product:1"]; !ok {
		t.Fatalf("cache key product:1 not written, keys = %v", c.data)
	}

	second := get(t, srv, "/products/1")
	if second.Code != http.StatusOK {
		t.Fatalf("second: status = %d, want 200", second.Code)
	}
	if h := second.Header().Get("X-Cache"); h != "HIT" {
		t.Fatalf("second: X-Cache = %q, want HIT", h)
	}
	if second.Body.String() != first.Body.String() {
		t.Fatalf("HIT body differs from MISS body:\n%s\n%s", second.Body.String(), first.Body.String())
	}
	if st.getCalls != 1 {
		t.Fatalf("store.GetProduct called %d times, want 1 (second request must be served from cache)", st.getCalls)
	}
}

func TestGetProductBypassWhenCacheDisabled(t *testing.T) {
	st := &fakeStore{products: map[int64]store.Product{1: keyboard}}
	srv := newTestServer(st, cache.Disabled{})

	for i := 0; i < 2; i++ {
		rec := get(t, srv, "/products/1")
		if rec.Code != http.StatusOK {
			t.Fatalf("status = %d, want 200", rec.Code)
		}
		if h := rec.Header().Get("X-Cache"); h != "BYPASS" {
			t.Fatalf("X-Cache = %q, want BYPASS", h)
		}
	}
	if st.getCalls != 2 {
		t.Fatalf("store.GetProduct called %d times, want 2 without a cache", st.getCalls)
	}
}

func TestGetProductNotFound(t *testing.T) {
	srv := newTestServer(&fakeStore{products: map[int64]store.Product{1: keyboard}}, newFakeCache())

	rec := get(t, srv, "/products/999")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
	var body map[string]string
	decode(t, rec, &body)
	if body["error"] != "not found" {
		t.Fatalf("body = %v, want {\"error\":\"not found\"}", body)
	}
}

func TestGetProductNonNumericID(t *testing.T) {
	srv := newTestServer(&fakeStore{products: map[int64]store.Product{1: keyboard}}, newFakeCache())

	for _, path := range []string{"/products/abc", "/products/0", "/products/-1", "/products/1.5"} {
		rec := get(t, srv, path)
		if rec.Code != http.StatusBadRequest {
			t.Errorf("%s: status = %d, want 400", path, rec.Code)
		}
	}
}

func TestListProducts(t *testing.T) {
	srv := newTestServer(&fakeStore{products: map[int64]store.Product{1: keyboard}}, newFakeCache())

	rec := get(t, srv, "/products")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var products []store.Product
	decode(t, rec, &products)
	if len(products) != 1 || products[0] != keyboard {
		t.Fatalf("body = %+v, want [%+v]", products, keyboard)
	}
	if rec.Header().Get("X-Cache") != "" {
		t.Fatalf("list must not carry X-Cache, got %q", rec.Header().Get("X-Cache"))
	}
}

func TestHealthz(t *testing.T) {
	srv := newTestServer(&fakeStore{pingErr: errors.New("down")}, newFakeCache())

	rec := get(t, srv, "/healthz")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 even when dependencies are down", rec.Code)
	}
	var body map[string]string
	decode(t, rec, &body)
	if body["status"] != "ok" {
		t.Fatalf("body = %v, want {\"status\":\"ok\"}", body)
	}
}

func TestReadyz(t *testing.T) {
	st := &fakeStore{products: map[int64]store.Product{}}
	srv := newTestServer(st, newFakeCache())

	rec := get(t, srv, "/readyz")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var ready readyResponse
	decode(t, rec, &ready)
	if ready.Status != "ready" || ready.Checks["database"] != "ok" || ready.Checks["cache"] != "ok" {
		t.Fatalf("body = %+v", ready)
	}

	st.pingErr = errors.New("connection refused")
	rec = get(t, srv, "/readyz")
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503 when the database ping fails", rec.Code)
	}
	decode(t, rec, &ready)
	if ready.Status != "not-ready" {
		t.Fatalf("status field = %q, want not-ready", ready.Status)
	}
	if !strings.Contains(ready.Checks["database"], "connection refused") {
		t.Fatalf("checks.database = %q, want the failing check named", ready.Checks["database"])
	}
	if ready.Checks["cache"] != "ok" {
		t.Fatalf("checks.cache = %q, want ok", ready.Checks["cache"])
	}
}

func TestMetrics(t *testing.T) {
	srv := newTestServer(&fakeStore{products: map[int64]store.Product{1: keyboard}}, newFakeCache())
	get(t, srv, "/products/1") // MISS
	get(t, srv, "/products/1") // HIT

	rec := get(t, srv, "/metrics")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	body := rec.Body.String()
	for _, want := range []string{
		"catalog_cache_hits_total 1",
		"catalog_cache_misses_total 1",
		`http_requests_total{method="GET",route="/products/{id}",status="200"} 2`,
		`http_request_duration_seconds_bucket{method="GET",route="/products/{id}",le="+Inf"} 2`,
		"go_goroutines",
	} {
		if !strings.Contains(body, want) {
			t.Errorf("metrics output lacks %q", want)
		}
	}
}

func TestUnknownRoute(t *testing.T) {
	srv := newTestServer(&fakeStore{}, newFakeCache())

	rec := get(t, srv, "/nope")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
	var body map[string]string
	decode(t, rec, &body)
	if body["error"] != "not found" {
		t.Fatalf("body = %v", body)
	}
}
