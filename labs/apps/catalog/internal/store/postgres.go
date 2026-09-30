// Package store reads products from PostgreSQL (labs/CONTRACT.md §4).
package store

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/trace"
)

// Product is one row of the products table; the JSON tags are the wire format of the API.
type Product struct {
	ID         int64  `json:"id"`
	SKU        string `json:"sku"`
	Name       string `json:"name"`
	PriceCents int32  `json:"price_cents"`
	Stock      int32  `json:"stock"`
}

// ErrNotFound is returned when no product has the requested id.
var ErrNotFound = errors.New("product not found")

// Store is what the HTTP layer needs; tests use an in-memory fake.
type Store interface {
	ListProducts(ctx context.Context) ([]Product, error)
	GetProduct(ctx context.Context, id int64) (Product, error)
	Ping(ctx context.Context) error
	Close()
}

const (
	sqlListProducts = `SELECT id, sku, name, price_cents, stock FROM products ORDER BY id`
	sqlGetProduct   = `SELECT id, sku, name, price_cents, stock FROM products WHERE id = $1`
)

// Postgres implements Store on top of a pgx connection pool.
type Postgres struct {
	pool   *pgxpool.Pool
	tracer trace.Tracer
}

// Connect builds the pool and waits until the database answers a ping, retrying with backoff for
// at most maxWait (the contract says 30 s). The returned error means "give up and exit 1".
func Connect(ctx context.Context, databaseURL string, maxWait time.Duration, logger *slog.Logger) (*Postgres, error) {
	cfg, err := pgxpool.ParseConfig(databaseURL)
	if err != nil {
		return nil, fmt.Errorf("parse DATABASE_URL: %w", err)
	}
	cfg.MaxConns = 10
	cfg.ConnConfig.ConnectTimeout = 5 * time.Second
	cfg.ConnConfig.RuntimeParams["application_name"] = "catalog"

	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, fmt.Errorf("create pool: %w", err)
	}

	deadline := time.Now().Add(maxWait)
	backoff := time.Second
	for {
		pingCtx, cancel := context.WithTimeout(ctx, 5*time.Second)
		err = pool.Ping(pingCtx)
		cancel()
		if err == nil {
			logger.InfoContext(ctx, "database connected")
			return &Postgres{pool: pool, tracer: otel.Tracer("shopfront/catalog/store")}, nil
		}
		if ctx.Err() != nil || time.Now().Add(backoff).After(deadline) {
			pool.Close()
			return nil, fmt.Errorf("database not reachable after %s: %w", maxWait, err)
		}
		logger.WarnContext(ctx, "database not ready, retrying", "error", err.Error(), "retry_in_seconds", backoff.Seconds())
		select {
		case <-ctx.Done():
			pool.Close()
			return nil, ctx.Err()
		case <-time.After(backoff):
		}
		backoff = min(backoff*2, 5*time.Second)
	}
}

func (p *Postgres) ListProducts(ctx context.Context) ([]Product, error) {
	ctx, span := p.startSpan(ctx, "SELECT shopfront.products")
	defer span.End()

	rows, err := p.pool.Query(ctx, sqlListProducts)
	if err != nil {
		return nil, p.fail(span, fmt.Errorf("list products: %w", err))
	}
	defer rows.Close()

	products := make([]Product, 0, 16)
	for rows.Next() {
		var pr Product
		if err := rows.Scan(&pr.ID, &pr.SKU, &pr.Name, &pr.PriceCents, &pr.Stock); err != nil {
			return nil, p.fail(span, fmt.Errorf("scan product: %w", err))
		}
		products = append(products, pr)
	}
	if err := rows.Err(); err != nil {
		return nil, p.fail(span, fmt.Errorf("list products: %w", err))
	}
	span.SetAttributes(attribute.Int("db.response.returned_rows", len(products)))
	return products, nil
}

func (p *Postgres) GetProduct(ctx context.Context, id int64) (Product, error) {
	ctx, span := p.startSpan(ctx, "SELECT shopfront.products")
	defer span.End()

	var pr Product
	err := p.pool.QueryRow(ctx, sqlGetProduct, id).Scan(&pr.ID, &pr.SKU, &pr.Name, &pr.PriceCents, &pr.Stock)
	if errors.Is(err, pgx.ErrNoRows) {
		return Product{}, ErrNotFound // a miss is a normal outcome, not a span error
	}
	if err != nil {
		return Product{}, p.fail(span, fmt.Errorf("get product %d: %w", id, err))
	}
	return pr, nil
}

// Ping is the readiness check: one round trip to the database.
func (p *Postgres) Ping(ctx context.Context) error { return p.pool.Ping(ctx) }

// Close waits for checked-out connections to be returned, then closes them.
func (p *Postgres) Close() { p.pool.Close() }

func (p *Postgres) startSpan(ctx context.Context, name string) (context.Context, trace.Span) {
	return p.tracer.Start(ctx, name,
		trace.WithSpanKind(trace.SpanKindClient),
		trace.WithAttributes(
			attribute.String("db.system", "postgresql"),
			attribute.String("db.namespace", "shopfront"),
			attribute.String("db.collection.name", "products"),
		),
	)
}

func (p *Postgres) fail(span trace.Span, err error) error {
	span.RecordError(err)
	span.SetStatus(codes.Error, "query failed")
	return err
}
