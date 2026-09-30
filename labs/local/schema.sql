-- shopfront schema (labs/CONTRACT.md §4). Idempotent: safe to run on every start.
-- Runs automatically on the first PostgreSQL start (docker-entrypoint-initdb.d) and again through
-- the db-migrate one-shot service, which mirrors how a migration task runs on ECS or Kubernetes.

CREATE TABLE IF NOT EXISTS products (
  id           BIGSERIAL PRIMARY KEY,
  sku          TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  price_cents  INTEGER NOT NULL CHECK (price_cents >= 0),
  stock        INTEGER NOT NULL CHECK (stock >= 0)
);

CREATE TABLE IF NOT EXISTS orders (
  id           UUID PRIMARY KEY,
  product_id   BIGINT NOT NULL REFERENCES products(id),
  quantity     INTEGER NOT NULL CHECK (quantity > 0),
  price_cents  INTEGER NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('CREATED','FULFILLED','FAILED')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS orders_status_created_idx ON orders (status, created_at DESC);

CREATE TABLE IF NOT EXISTS daily_stats (
  day            DATE PRIMARY KEY,
  orders_count   BIGINT NOT NULL DEFAULT 0,
  revenue_cents  BIGINT NOT NULL DEFAULT 0
);
