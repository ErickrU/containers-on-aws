/**
 * Prometheus metrics (labs/CONTRACT.md §6). One Registry per app instance keeps tests independent.
 */
import { Counter, Histogram, Registry, collectDefaultMetrics } from 'prom-client';

export interface Metrics {
  registry: Registry;
  httpRequests: Counter<'method' | 'route' | 'status'>;
  httpDuration: Histogram<'method' | 'route'>;
  ordersCreated: Counter<string>;
  ordersFailed: Counter<string>;
}

export function createMetrics(): Metrics {
  const registry = new Registry();
  collectDefaultMetrics({ register: registry });
  return {
    registry,
    httpRequests: new Counter({
      name: 'http_requests_total',
      help: 'HTTP requests handled, by method, route pattern and status code.',
      labelNames: ['method', 'route', 'status'],
      registers: [registry],
    }),
    httpDuration: new Histogram({
      name: 'http_request_duration_seconds',
      help: 'HTTP request latency in seconds, by method and route pattern.',
      labelNames: ['method', 'route'],
      buckets: [0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
      registers: [registry],
    }),
    ordersCreated: new Counter({
      name: 'orders_created_total',
      help: 'Orders inserted with status CREATED and queued for fulfillment.',
      registers: [registry],
    }),
    ordersFailed: new Counter({
      name: 'orders_failed_total',
      help: 'POST /orders requests that failed after validation (catalog, database or queue errors).',
      registers: [registry],
    }),
  };
}
