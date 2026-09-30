/**
 * Behavioural tests of the orders API through buildApp + app.inject(): no network, no database,
 * no queue. Run with `npm test` (node --test through tsx).
 */
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, describe, it } from 'node:test';

import type { SendMessageCommandInput } from '@aws-sdk/client-sqs';
import { trace } from '@opentelemetry/api';
import { node as sdkTraceNode } from '@opentelemetry/sdk-node';
import type { FastifyInstance } from 'fastify';

import { buildApp } from '../src/app.js';
import type { CatalogClient, Product } from '../src/catalog-client.js';
import { CatalogUnavailableError } from '../src/catalog-client.js';
import type { Db, NewOrder, Order, OrderStatus } from '../src/db.js';
import { createMetrics } from '../src/metrics.js';
import { SqsPublisher, createPublishers, type EventPublisher, type OrderCreatedEvent } from '../src/publishers.js';

// ---- fakes ---------------------------------------------------------------------------------------

class FakeDb implements Db {
  orders = new Map<string, Order>();
  pingError: Error | undefined;

  async ping(): Promise<void> {
    if (this.pingError) throw this.pingError;
  }

  async insertOrder(order: NewOrder): Promise<Order> {
    const now = new Date().toISOString();
    const row: Order = { ...order, status: 'CREATED', createdAt: now, updatedAt: now };
    this.orders.set(order.id, row);
    return row;
  }

  async getOrder(id: string): Promise<Order | null> {
    return this.orders.get(id) ?? null;
  }

  async listOrders(status?: OrderStatus, limit = 50): Promise<Order[]> {
    return [...this.orders.values()]
      .filter((o) => !status || o.status === status)
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .slice(0, limit);
  }

  async end(): Promise<void> {}
}

class FakeCatalog implements CatalogClient {
  unavailable = false;
  constructor(private readonly products: Record<number, Product>) {}

  async getProduct(id: number): Promise<Product | null> {
    if (this.unavailable) throw new CatalogUnavailableError('catalog unavailable after 2 attempts');
    return this.products[id] ?? null;
  }
}

class FakeSqs {
  sent: SendMessageCommandInput[] = [];
  failWith: Error | undefined;

  send = async (input: SendMessageCommandInput): Promise<unknown> => {
    if (this.failWith) throw this.failWith;
    this.sent.push(input);
    return { MessageId: randomUUID() };
  };
}

class FakeKafka implements EventPublisher {
  published: Array<{ event: OrderCreatedEvent; headers: Record<string, string> }> = [];
  async publish(event: OrderCreatedEvent): Promise<void> {
    this.published.push({ event, headers: {} });
  }
  async close(): Promise<void> {}
}

const KEYBOARD: Product = { id: 1, sku: 'KB-MECH-87', name: 'Mechanical keyboard, 87 keys', price_cents: 8999, stock: 120 };
const CHAIR: Product = { id: 8, sku: 'CHAIR-ERGO-M', name: 'Ergonomic office chair, medium', price_cents: 28900, stock: 15 };
const QUEUE_URL = 'http://elasticmq:9324/000000000000/orders-created';

const silentLogger = {
  level: 'silent',
  fatal() {},
  error() {},
  warn() {},
  info() {},
  debug() {},
  trace() {},
  silent() {},
  child() {
    return silentLogger;
  },
};

function harness() {
  const db = new FakeDb();
  const catalog = new FakeCatalog({ 1: KEYBOARD, 8: CHAIR });
  const sqs = new FakeSqs();
  const kafka = new FakeKafka();
  const metrics = createMetrics();
  const publishers = createPublishers({
    sqs: new SqsPublisher(sqs.send, QUEUE_URL),
    kafka,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    logger: silentLogger as any,
  });
  const app = buildApp({ db, catalog, publishers, metrics });
  return { app, db, catalog, sqs, kafka, metrics };
}

// A real tracer provider (no exporter) so a span is active during the request and the publisher
// has a W3C trace context to inject, exactly like in production behind the auto-instrumentation.
const provider = new sdkTraceNode.NodeTracerProvider();
const tracer = trace.getTracer('orders-test');

function inTrace<T>(fn: () => Promise<T>): Promise<T> {
  return tracer.startActiveSpan('POST /orders', async (span) => {
    try {
      return await fn();
    } finally {
      span.end();
    }
  });
}

describe('orders API', () => {
  let app: FastifyInstance;
  let h: ReturnType<typeof harness>;

  before(async () => {
    provider.register();
    h = harness();
    app = h.app;
    await app.ready();
  });

  after(async () => {
    await app.close();
    await provider.shutdown();
  });

  it('POST /orders creates the order, queues it on SQS with traceparent, and produces to Kafka', async () => {
    const res = await inTrace(() =>
      app.inject({ method: 'POST', url: '/orders', payload: { productId: 1, quantity: 2 } }),
    );
    assert.equal(res.statusCode, 201, res.body);
    const body = res.json();
    assert.match(body.id, /^[0-9a-f-]{36}$/);
    assert.equal(body.status, 'CREATED');
    assert.equal(body.productId, 1);
    assert.equal(body.quantity, 2);
    assert.equal(body.priceCents, 8999);
    assert.ok(typeof body.createdAt === 'string' && !Number.isNaN(Date.parse(body.createdAt)));

    // stored
    const stored = await h.db.getOrder(body.id);
    assert.equal(stored?.status, 'CREATED');

    // SQS message per contract §5
    assert.equal(h.sqs.sent.length, 1);
    const message = h.sqs.sent[0]!;
    assert.equal(message.QueueUrl, QUEUE_URL);
    const event = JSON.parse(message.MessageBody ?? '{}');
    assert.deepEqual(event, {
      type: 'order.created',
      version: 1,
      orderId: body.id,
      productId: 1,
      quantity: 2,
      priceCents: 8999,
      createdAt: body.createdAt,
    });
    const traceparent = message.MessageAttributes?.traceparent;
    assert.ok(traceparent, `traceparent attribute missing: ${JSON.stringify(message.MessageAttributes)}`);
    assert.equal(traceparent.DataType, 'String');
    assert.match(traceparent.StringValue ?? '', /^00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]$/);

    // Kafka gets the same event
    assert.equal(h.kafka.published.length, 1);
    assert.deepEqual(h.kafka.published[0]!.event, event);
  });

  it('POST /orders answers 404 for an unknown product', async () => {
    const res = await app.inject({ method: 'POST', url: '/orders', payload: { productId: 999, quantity: 1 } });
    assert.equal(res.statusCode, 404);
    assert.deepEqual(res.json(), { error: 'product not found' });
    assert.equal(h.sqs.sent.length, 1, 'no message must be sent');
  });

  it('POST /orders answers 409 when quantity exceeds stock', async () => {
    const res = await app.inject({ method: 'POST', url: '/orders', payload: { productId: 8, quantity: 16 } });
    assert.equal(res.statusCode, 409);
    assert.equal(res.json().available, 15);
  });

  it('POST /orders answers 400 on validation errors', async () => {
    const bad = [
      { productId: 1 },
      { quantity: 1 },
      { productId: 0, quantity: 1 },
      { productId: 1, quantity: 0 },
      { productId: 1.5, quantity: 1 },
      { productId: 'one', quantity: 1 },
    ];
    for (const payload of bad) {
      const res = await app.inject({ method: 'POST', url: '/orders', payload });
      assert.equal(res.statusCode, 400, `payload ${JSON.stringify(payload)} -> ${res.body}`);
      assert.ok(typeof res.json().error === 'string');
    }
    const malformed = await app.inject({
      method: 'POST',
      url: '/orders',
      headers: { 'content-type': 'application/json' },
      payload: '{not json',
    });
    assert.equal(malformed.statusCode, 400);
  });

  it('POST /orders answers 502 when the catalog is unavailable', async () => {
    h.catalog.unavailable = true;
    try {
      const res = await app.inject({ method: 'POST', url: '/orders', payload: { productId: 1, quantity: 1 } });
      assert.equal(res.statusCode, 502);
      assert.deepEqual(res.json(), { error: 'catalog unavailable' });
    } finally {
      h.catalog.unavailable = false;
    }
  });

  it('POST /orders answers 500 (order stored) when SQS fails', async () => {
    h.sqs.failWith = new Error('SQS unreachable');
    try {
      const res = await app.inject({ method: 'POST', url: '/orders', payload: { productId: 1, quantity: 1 } });
      assert.equal(res.statusCode, 500);
      const body = res.json();
      assert.match(body.error, /could not be queued/);
      assert.equal((await h.db.getOrder(body.id))?.status, 'CREATED');
    } finally {
      h.sqs.failWith = undefined;
    }
  });

  it('GET /orders/:id answers 404 for unknown and malformed ids', async () => {
    for (const id of [randomUUID(), 'not-a-uuid', '42']) {
      const res = await app.inject({ method: 'GET', url: `/orders/${id}` });
      assert.equal(res.statusCode, 404, id);
      assert.deepEqual(res.json(), { error: 'not found' });
    }
  });

  it('GET /orders/:id and GET /orders?status= return stored orders', async () => {
    const created = (
      await app.inject({ method: 'POST', url: '/orders', payload: { productId: 1, quantity: 3 } })
    ).json();
    const one = await app.inject({ method: 'GET', url: `/orders/${created.id}` });
    assert.equal(one.statusCode, 200);
    assert.equal(one.json().id, created.id);
    assert.equal(one.json().status, 'CREATED');

    const list = await app.inject({ method: 'GET', url: '/orders?status=CREATED' });
    assert.equal(list.statusCode, 200);
    assert.ok(list.json().some((o: { id: string }) => o.id === created.id));

    const fulfilled = await app.inject({ method: 'GET', url: '/orders?status=FULFILLED' });
    assert.deepEqual(fulfilled.json(), []);

    const invalid = await app.inject({ method: 'GET', url: '/orders?status=SHIPPED' });
    assert.equal(invalid.statusCode, 400);
  });

  it('GET /healthz is 200 even when the database is down', async () => {
    h.db.pingError = new Error('connection refused');
    try {
      const res = await app.inject({ method: 'GET', url: '/healthz' });
      assert.equal(res.statusCode, 200);
      assert.deepEqual(res.json(), { status: 'ok' });
    } finally {
      h.db.pingError = undefined;
    }
  });

  it('GET /readyz is 503 naming the database when the ping rejects, 200 otherwise', async () => {
    h.db.pingError = new Error('connection refused');
    try {
      const res = await app.inject({ method: 'GET', url: '/readyz' });
      assert.equal(res.statusCode, 503);
      const body = res.json();
      assert.equal(body.status, 'not-ready');
      assert.match(body.checks.database, /^error: connection refused/);
    } finally {
      h.db.pingError = undefined;
    }
    const ok = await app.inject({ method: 'GET', url: '/readyz' });
    assert.equal(ok.statusCode, 200);
    assert.deepEqual(ok.json(), { status: 'ready', checks: { database: 'ok' } });
  });

  it('GET /metrics exposes the contract counters in Prometheus text format', async () => {
    const res = await app.inject({ method: 'GET', url: '/metrics' });
    assert.equal(res.statusCode, 200);
    assert.match(res.headers['content-type'] as string, /^text\/plain/);
    assert.match(res.body, /^orders_created_total \d+$/m);
    assert.match(res.body, /^orders_failed_total \d+$/m);
    assert.match(res.body, /^http_requests_total\{method="POST",route="\/orders",status="201"\} \d+$/m);
    assert.match(res.body, /^http_request_duration_seconds_bucket\{/m);
    assert.match(res.body, /^process_cpu_user_seconds_total /m);
  });

  it('unknown routes answer a JSON 404', async () => {
    const res = await app.inject({ method: 'GET', url: '/nope' });
    assert.equal(res.statusCode, 404);
    assert.deepEqual(res.json(), { error: 'not found' });
  });
});
