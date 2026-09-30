/**
 * buildApp wires routes, hooks and error handling around injected dependencies, so the same
 * application runs against PostgreSQL/SQS/Kafka in production and against fakes in tests.
 */
import { context as otelContext } from '@opentelemetry/api';
import { RPCType, getRPCMetadata } from '@opentelemetry/core';
import Fastify, { LogController, type FastifyBaseLogger, type FastifyError, type FastifyInstance } from 'fastify';

import { CatalogUnavailableError, type CatalogClient } from './catalog-client.js';
import type { Db } from './db.js';
import { PROBE_ROUTES, registerHealthRoutes } from './health.js';
import { createMetrics, type Metrics } from './metrics.js';
import type { Publishers } from './publishers.js';
import { registerOrderRoutes } from './routes.js';

export interface AppDeps {
  db: Db;
  catalog: CatalogClient;
  publishers: Publishers;
  metrics?: Metrics;
  /** The pino instance from logger.ts; tests leave it unset for a silent app. */
  logger?: FastifyBaseLogger;
}

export function buildApp(deps: AppDeps): FastifyInstance {
  const metrics = deps.metrics ?? createMetrics();
  const app = Fastify({
    ...(deps.logger ? { loggerInstance: deps.logger } : { logger: false }),
    // Fastify's own "incoming request"/"request completed" lines are replaced by the one-line
    // summary in the onResponse hook below.
    logController: new LogController({ disableRequestLogging: true }),
    forceCloseConnections: 'idle', // on close: drop idle keep-alive connections, finish in-flight requests
  });

  // Tell the HTTP instrumentation which route matched: it renames the server span from "POST" to
  // "POST /orders" and sets http.route when the response ends (labs/CONTRACT.md §6 span names).
  // No-op when tracing is off or the request did not go through the instrumentation (tests).
  app.addHook('onRequest', async (request) => {
    const rpcMetadata = getRPCMetadata(otelContext.active());
    if (rpcMetadata?.type === RPCType.HTTP && request.routeOptions.url) {
      rpcMetadata.route = request.routeOptions.url;
    }
  });

  // One log line and two metrics per request, labelled with the route pattern (bounded cardinality).
  app.addHook('onResponse', async (request, reply) => {
    const route = request.routeOptions.url ?? 'unknown';
    const status = reply.statusCode;
    metrics.httpRequests.inc({ method: request.method, route, status: String(status) });
    metrics.httpDuration.observe({ method: request.method, route }, reply.elapsedTime / 1000);
    const fields = { method: request.method, route, status, duration_ms: Math.round(reply.elapsedTime * 1000) / 1000 };
    if (PROBE_ROUTES.has(route)) {
      request.log.debug(fields, 'http request'); // probes and scrapes would flood the log at info
    } else {
      request.log.info(fields, 'http request');
    }
  });

  app.setNotFoundHandler(async (_request, reply) => reply.code(404).send({ error: 'not found' }));

  app.setErrorHandler(async (error: unknown, request, reply) => {
    const err = error instanceof Error ? error : new Error(String(error));
    const { validation, statusCode } = err as Partial<FastifyError>;
    if (validation) {
      return reply.code(400).send({ error: err.message });
    }
    if (err instanceof CatalogUnavailableError) {
      metrics.ordersFailed.inc();
      request.log.error({ error: err.message }, 'catalog unavailable');
      return reply.code(502).send({ error: 'catalog unavailable' });
    }
    if (typeof statusCode === 'number' && statusCode >= 400 && statusCode < 500) {
      // malformed JSON body, unsupported media type, payload too large, ...
      return reply.code(statusCode).send({ error: err.message });
    }
    if (request.method === 'POST' && route(request) === '/orders') {
      metrics.ordersFailed.inc();
    }
    request.log.error({ error: err.message, stack: err.stack }, 'unhandled error');
    return reply.code(500).send({ error: 'internal error' });
  });

  registerHealthRoutes(app, { db: deps.db, metrics });
  registerOrderRoutes(app, { db: deps.db, catalog: deps.catalog, publishers: deps.publishers, metrics });

  return app;
}

function route(request: { routeOptions: { url?: string } }): string {
  return request.routeOptions.url ?? 'unknown';
}
