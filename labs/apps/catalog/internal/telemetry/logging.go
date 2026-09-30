package telemetry

import (
	"context"
	"io"
	"log/slog"
	"strings"
	"time"

	"go.opentelemetry.io/otel/trace"
)

// NewLogger returns a JSON logger writing one object per line with the fields the contract asks
// for: time (UTC, RFC 3339 with milliseconds), level (debug|info|warn|error), msg, service and,
// while a span is active in the context passed to the log call, trace_id and span_id.
func NewLogger(w io.Writer, level slog.Level, service string) *slog.Logger {
	handler := slog.NewJSONHandler(w, &slog.HandlerOptions{
		Level:       level,
		ReplaceAttr: replaceAttr,
	})
	return slog.New(traceHandler{Handler: handler}).With("service", service)
}

func replaceAttr(groups []string, a slog.Attr) slog.Attr {
	if len(groups) > 0 {
		return a
	}
	switch a.Key {
	case slog.TimeKey:
		if t, ok := a.Value.Any().(time.Time); ok {
			a.Value = slog.StringValue(t.UTC().Format("2006-01-02T15:04:05.000Z07:00"))
		}
	case slog.LevelKey:
		if l, ok := a.Value.Any().(slog.Level); ok {
			// Same vocabulary as LOG_LEVEL so every shopfront service emits identical labels.
			a.Value = slog.StringValue(strings.ToLower(l.String()))
		}
	}
	return a
}

// traceHandler decorates records with the active span's identifiers so a log line can be found
// from a trace and a trace from a log line.
type traceHandler struct {
	slog.Handler
}

func (h traceHandler) Handle(ctx context.Context, r slog.Record) error {
	if sc := trace.SpanContextFromContext(ctx); sc.IsValid() {
		r.AddAttrs(
			slog.String("trace_id", sc.TraceID().String()),
			slog.String("span_id", sc.SpanID().String()),
		)
	}
	return h.Handler.Handle(ctx, r)
}

func (h traceHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return traceHandler{Handler: h.Handler.WithAttrs(attrs)}
}

func (h traceHandler) WithGroup(name string) slog.Handler {
	return traceHandler{Handler: h.Handler.WithGroup(name)}
}
