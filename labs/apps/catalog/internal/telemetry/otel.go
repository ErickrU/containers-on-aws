// Package telemetry wires traces (OpenTelemetry), metrics (Prometheus) and logs (slog) for the
// catalog service (labs/CONTRACT.md §6).
package telemetry

import (
	"context"
	"fmt"
	"log/slog"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.26.0"
)

// SetupTracing installs W3C trace-context propagation and, when endpoint is non-empty, a tracer
// provider that exports OTLP over HTTP. With an empty endpoint the process runs with the no-op
// tracer: spans cost nothing and log lines carry no trace_id.
//
// The exporter reads OTEL_EXPORTER_OTLP_ENDPOINT from the environment itself (and appends
// /v1/traces), exactly like the Python and Node SDKs do, so the same variable works everywhere.
// The returned function flushes queued spans and must be called during shutdown.
func SetupTracing(ctx context.Context, serviceName, endpoint string, logger *slog.Logger) (func(context.Context) error, error) {
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))
	otel.SetErrorHandler(otel.ErrorHandlerFunc(func(err error) {
		logger.Warn("opentelemetry error", "error", err.Error())
	}))

	if endpoint == "" {
		logger.Info("tracing disabled: OTEL_EXPORTER_OTLP_ENDPOINT is not set")
		return func(context.Context) error { return nil }, nil
	}

	exporter, err := otlptracehttp.New(ctx)
	if err != nil {
		return nil, fmt.Errorf("create OTLP trace exporter: %w", err)
	}

	// WithFromEnv reads OTEL_RESOURCE_ATTRIBUTES (deployment.environment=...); the explicit
	// service.name wins over anything the environment says because it is listed last.
	res, err := resource.New(ctx,
		resource.WithFromEnv(),
		resource.WithTelemetrySDK(),
		resource.WithAttributes(semconv.ServiceName(serviceName)),
	)
	if err != nil {
		// resource.New returns a usable partial resource together with the error.
		logger.Warn("resource detection incomplete", "error", err.Error())
	}

	provider := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)
	otel.SetTracerProvider(provider)
	logger.Info("tracing enabled", "otlp_endpoint", endpoint, "service_name", serviceName)
	return provider.Shutdown, nil
}
