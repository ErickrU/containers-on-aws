/**
 * PostgreSQL access through pg (labs/CONTRACT.md §4). SQL is parameterized and matches
 * labs/local/schema.sql. Tests use an in-memory implementation of the Db interface.
 */
import type { FastifyBaseLogger } from 'fastify';
import { Pool } from 'pg';

export const ORDER_STATUSES = ['CREATED', 'FULFILLED', 'FAILED'] as const;
export type OrderStatus = (typeof ORDER_STATUSES)[number];

export interface Order {
  id: string;
  productId: number;
  quantity: number;
  priceCents: number;
  status: OrderStatus;
  createdAt: string; // ISO 8601, UTC
  updatedAt: string;
}

export interface NewOrder {
  id: string;
  productId: number;
  quantity: number;
  priceCents: number;
}

export interface Db {
  /** Readiness check: one round trip (SELECT 1). */
  ping(): Promise<void>;
  insertOrder(order: NewOrder): Promise<Order>;
  getOrder(id: string): Promise<Order | null>;
  listOrders(status?: OrderStatus, limit?: number): Promise<Order[]>;
  end(): Promise<void>;
}

interface OrderRow {
  id: string;
  product_id: string | number; // BIGINT arrives as a string from pg
  quantity: number;
  price_cents: number;
  status: OrderStatus;
  created_at: Date;
  updated_at: Date;
}

const ORDER_COLUMNS = 'id, product_id, quantity, price_cents, status, created_at, updated_at';

const SQL_INSERT_ORDER =
  `INSERT INTO orders (id, product_id, quantity, price_cents, status) ` +
  `VALUES ($1, $2, $3, $4, 'CREATED') RETURNING ${ORDER_COLUMNS}`;
const SQL_GET_ORDER = `SELECT ${ORDER_COLUMNS} FROM orders WHERE id = $1`;
const SQL_LIST_ORDERS =
  `SELECT ${ORDER_COLUMNS} FROM orders WHERE ($1::text IS NULL OR status = $1) ` +
  `ORDER BY created_at DESC LIMIT $2`;

function toOrder(row: OrderRow): Order {
  return {
    id: row.id,
    productId: Number(row.product_id),
    quantity: row.quantity,
    priceCents: row.price_cents,
    status: row.status,
    createdAt: row.created_at.toISOString(),
    updatedAt: row.updated_at.toISOString(),
  };
}

export class PostgresDb implements Db {
  constructor(private readonly pool: Pool) {}

  async ping(): Promise<void> {
    await this.pool.query('SELECT 1');
  }

  async insertOrder(order: NewOrder): Promise<Order> {
    const result = await this.pool.query<OrderRow>(SQL_INSERT_ORDER, [
      order.id,
      order.productId,
      order.quantity,
      order.priceCents,
    ]);
    return toOrder(result.rows[0]!);
  }

  async getOrder(id: string): Promise<Order | null> {
    const result = await this.pool.query<OrderRow>(SQL_GET_ORDER, [id]);
    return result.rows[0] ? toOrder(result.rows[0]) : null;
  }

  async listOrders(status?: OrderStatus, limit = 50): Promise<Order[]> {
    const result = await this.pool.query<OrderRow>(SQL_LIST_ORDERS, [status ?? null, limit]);
    return result.rows.map(toOrder);
  }

  async end(): Promise<void> {
    await this.pool.end();
  }

  /**
   * An idle client that loses its connection emits 'error' on the pool; without a listener that
   * would crash the process. The listener logs it and the pool replaces the client on next use.
   */
  onIdleClientError(listener: (err: Error) => void): void {
    this.pool.on('error', listener);
  }
}

/** Builds the pool. Nothing connects until the first query, so this never throws on a down database. */
export function createDb(databaseUrl: string): PostgresDb {
  const pool = new Pool({
    connectionString: databaseUrl,
    max: 10,
    connectionTimeoutMillis: 5_000,
    idleTimeoutMillis: 30_000,
    application_name: 'orders',
  });
  return new PostgresDb(pool);
}

/**
 * Start-up rule from the contract §7: retry the ping with backoff for up to maxWaitMs (30 s), then
 * give up. The caller exits 1 when this rejects.
 */
export async function waitForDatabase(db: Db, logger: FastifyBaseLogger, maxWaitMs = 30_000): Promise<void> {
  const deadline = Date.now() + maxWaitMs;
  let backoffMs = 1_000;
  for (;;) {
    try {
      await db.ping();
      logger.info('database connected');
      return;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (Date.now() + backoffMs > deadline) {
        throw new Error(`database not reachable after ${maxWaitMs / 1000}s: ${message}`);
      }
      logger.warn({ error: message, retry_in_seconds: backoffMs / 1000 }, 'database not ready, retrying');
      await new Promise((resolve) => setTimeout(resolve, backoffMs));
      backoffMs = Math.min(backoffMs * 2, 5_000);
    }
  }
}
