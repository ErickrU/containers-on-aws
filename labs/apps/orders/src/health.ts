/**
 * /healthz, /readyz and /metrics (labs/CONTRACT.md §3 and §6).
 *
 * Liveness answers while the event loop turns. Readiness pings the database and returns 503 naming
 * the failing check: the load balancer stops sending traffic, the platform does not restart the task.
 */
import type { FastifyInstance } from 'fastify';

import type { Db } from './db.js';
import type { Metrics } from './metrics.js';

export const PROBE_ROUTES = new Set(['/healthz', '/readyz', '/metrics']);

const READY_CHECK_TIMEOUT_MS = 2_000;

async function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`timed out after ${ms} ms`)), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}

export function registerHealthRoutes(app: FastifyInstance, deps: { db: Db; metrics: Metrics }): void {
  app.get('/healthz', async () => ({ status: 'ok' }));

  app.get('/readyz', async (_request, reply) => {
    const checks: Record<string, string> = {};
    try {
      await withTimeout(deps.db.ping(), READY_CHECK_TIMEOUT_MS);
      checks.database = 'ok';
    } catch (err) {
      checks.database = `error: ${err instanceof Error ? err.message : String(err)}`;
    }
    const ready = Object.values(checks).every((value) => value === 'ok');
    if (!ready) {
      app.log.warn({ checks }, 'readiness check failed');
    }
    return reply.code(ready ? 200 : 503).send({ status: ready ? 'ready' : 'not-ready', checks });
  });

  app.get('/metrics', async (_request, reply) => {
    reply.header('content-type', deps.metrics.registry.contentType);
    return deps.metrics.registry.metrics();
  });
}
