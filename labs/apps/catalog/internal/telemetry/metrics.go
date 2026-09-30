package telemetry

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Metrics holds the Prometheus registry and the application counters listed in
// labs/CONTRACT.md §6. A fresh registry per instance keeps tests independent of each other.
type Metrics struct {
	registry *prometheus.Registry

	HTTPRequests *prometheus.CounterVec   // http_requests_total{method,route,status}
	HTTPDuration *prometheus.HistogramVec // http_request_duration_seconds{method,route}
	CacheHits    prometheus.Counter       // catalog_cache_hits_total
	CacheMisses  prometheus.Counter       // catalog_cache_misses_total
}

// NewMetrics registers the application metrics plus the default Go runtime and process collectors.
func NewMetrics() *Metrics {
	m := &Metrics{
		registry: prometheus.NewRegistry(),
		HTTPRequests: prometheus.NewCounterVec(prometheus.CounterOpts{
			Name: "http_requests_total",
			Help: "HTTP requests handled, by method, route pattern and status code.",
		}, []string{"method", "route", "status"}),
		HTTPDuration: prometheus.NewHistogramVec(prometheus.HistogramOpts{
			Name:    "http_request_duration_seconds",
			Help:    "HTTP request latency in seconds, by method and route pattern.",
			Buckets: []float64{.001, .0025, .005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5},
		}, []string{"method", "route"}),
		CacheHits: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "catalog_cache_hits_total",
			Help: "Product lookups answered from Valkey.",
		}),
		CacheMisses: prometheus.NewCounter(prometheus.CounterOpts{
			Name: "catalog_cache_misses_total",
			Help: "Product lookups that went to PostgreSQL and then filled the cache.",
		}),
	}
	m.registry.MustRegister(
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
		m.HTTPRequests,
		m.HTTPDuration,
		m.CacheHits,
		m.CacheMisses,
	)
	return m
}

// Handler serves the registry in Prometheus text format for GET /metrics.
func (m *Metrics) Handler() http.Handler {
	return promhttp.HandlerFor(m.registry, promhttp.HandlerOpts{})
}
