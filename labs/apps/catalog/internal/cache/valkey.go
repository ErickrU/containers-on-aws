// Package cache is the cache-aside layer in front of PostgreSQL (labs/CONTRACT.md §3 and §4).
//
// Keys are product:{id}, values the JSON of the product, TTL CACHE_TTL_SECONDS. The cache is
// optional: when VALKEY_URL is unset the Disabled implementation is used and every lookup reports
// BYPASS, so the service degrades to "always PostgreSQL" instead of failing.
package cache

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

// ErrDisabled is returned by Disabled: no cache is configured for this process.
var ErrDisabled = errors.New("cache disabled")

// Cache is what the HTTP layer needs; tests use an in-memory fake.
type Cache interface {
	// Get returns (nil, nil) on a miss and (nil, err) when the cache is unavailable or disabled.
	Get(ctx context.Context, key string) ([]byte, error)
	Set(ctx context.Context, key string, value []byte, ttl time.Duration) error
	Ping(ctx context.Context) error
	Close() error
}

// Disabled is the no-op used when VALKEY_URL is unset.
type Disabled struct{}

func (Disabled) Get(context.Context, string) ([]byte, error)              { return nil, ErrDisabled }
func (Disabled) Set(context.Context, string, []byte, time.Duration) error { return ErrDisabled }
func (Disabled) Ping(context.Context) error                               { return ErrDisabled }
func (Disabled) Close() error                                             { return nil }

// Valkey talks the Redis protocol to Valkey (or ElastiCache) through go-redis.
type Valkey struct {
	client *redis.Client
}

// NewValkey parses a redis:// or rediss:// URL. Timeouts are short on purpose: a slow cache must
// not make product lookups slower than going straight to PostgreSQL.
func NewValkey(rawURL string) (*Valkey, error) {
	opts, err := redis.ParseURL(rawURL)
	if err != nil {
		return nil, fmt.Errorf("parse VALKEY_URL: %w", err)
	}
	opts.ClientName = "catalog"
	opts.DialTimeout = 2 * time.Second
	opts.ReadTimeout = time.Second
	opts.WriteTimeout = time.Second
	opts.MaxRetries = 1
	return &Valkey{client: redis.NewClient(opts)}, nil
}

func (v *Valkey) Get(ctx context.Context, key string) ([]byte, error) {
	b, err := v.client.Get(ctx, key).Bytes()
	if errors.Is(err, redis.Nil) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("cache get: %w", err)
	}
	return b, nil
}

func (v *Valkey) Set(ctx context.Context, key string, value []byte, ttl time.Duration) error {
	if err := v.client.Set(ctx, key, value, ttl).Err(); err != nil {
		return fmt.Errorf("cache set: %w", err)
	}
	return nil
}

// Ping is the readiness check for the cache.
func (v *Valkey) Ping(ctx context.Context) error { return v.client.Ping(ctx).Err() }

func (v *Valkey) Close() error { return v.client.Close() }
