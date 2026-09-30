/**
 * Business endpoints of the orders service (labs/CONTRACT.md §3).
 *
 * POST /orders: validate -> ask catalog -> 404/409 -> INSERT status CREATED -> SQS -> Kafka -> 201.
 * GET /orders/:id and GET /orders?status= read from PostgreSQL.
 */
import { randomUUID } from 'node:crypto';

import type { FastifyInstance } from 'fastify';

import type { CatalogClient } from './catalog-client.js';
import { ORDER_STATUSES, type Db, type Order, type OrderStatus } from './db.js';
import type { Metrics } from './metrics.js';
import { orderCreatedEvent, type Publishers } from './publishers.js';

export interface RouteDeps {
  db: Db;
  catalog: CatalogClient;
  publishers: Publishers;
  metrics: Metrics;
}

interface CreateOrderBody {
  productId: number;
  quantity: number;
}

const createOrderSchema = {
  body: {
    type: 'object',
    required: ['productId', 'quantity'],
    properties: {
      productId: { type: 'integer', minimum: 1 },
      quantity: { type: 'integer', minimum: 1 },
    },
  },
} as const;

const listOrdersSchema = {
  querystring: {
    type: 'object',
    properties: {
      status: { type: 'string', enum: ORDER_STATUSES },
    },
  },
} as const;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The response shape of the contract: camelCase, no updatedAt on creation. */
function orderResponse(order: Order) {
  return {
    id: order.id,
    productId: order.productId,
    quantity: order.quantity,
    priceCents: order.priceCents,
    status: order.status,
    createdAt: order.createdAt,
  };
}

export function registerOrderRoutes(app: FastifyInstance, deps: RouteDeps): void {
  app.post<{ Body: CreateOrderBody }>('/orders', { schema: createOrderSchema }, async (request, reply) => {
    const { productId, quantity } = request.body;

    // CatalogUnavailableError propagates to the error handler, which answers 502.
    const product = await deps.catalog.getProduct(productId);
    if (!product) {
      return reply.code(404).send({ error: 'product not found' });
    }
    if (quantity > product.stock) {
      return reply.code(409).send({ error: 'insufficient stock', available: product.stock });
    }

    const order = await deps.db.insertOrder({
      id: randomUUID(),
      productId,
      quantity,
      priceCents: product.price_cents,
    });

    try {
      await deps.publishers.publishOrderCreated(orderCreatedEvent(order));
    } catch (err) {
      // The row exists with status CREATED but no message reached the queue, so nothing will
      // fulfil it. Reported as 500 with the id so an operator can requeue or fail it by hand.
      deps.metrics.ordersFailed.inc();
      request.log.error(
        { order_id: order.id, error: err instanceof Error ? err.message : String(err) },
        'order stored but the SQS message could not be sent',
      );
      return reply.code(500).send({ error: 'order stored but could not be queued for fulfillment', id: order.id });
    }

    deps.metrics.ordersCreated.inc();
    request.log.info(
      { order_id: order.id, product_id: productId, quantity, price_cents: order.priceCents },
      'order created',
    );
    return reply.code(201).send(orderResponse(order));
  });

  app.get<{ Params: { id: string } }>('/orders/:id', async (request, reply) => {
    const { id } = request.params;
    // Anything that is not a UUID cannot be an order id; treating it as 404 keeps the database
    // from raising "invalid input syntax for type uuid".
    const order = UUID.test(id) ? await deps.db.getOrder(id.toLowerCase()) : null;
    if (!order) {
      return reply.code(404).send({ error: 'not found' });
    }
    return { ...orderResponse(order), updatedAt: order.updatedAt };
  });

  app.get<{ Querystring: { status?: OrderStatus } }>('/orders', { schema: listOrdersSchema }, async (request) => {
    const orders = await deps.db.listOrders(request.query.status, 50);
    return orders.map((order) => ({ ...orderResponse(order), updatedAt: order.updatedAt }));
  });
}
