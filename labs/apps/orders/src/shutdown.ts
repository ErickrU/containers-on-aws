/**
 * Graceful shutdown (labs/CONTRACT.md §7).
 *
 * SIGTERM (platform stop) or SIGINT (Ctrl-C): stop accepting connections and finish in-flight
 * requests (app.close), disconnect the Kafka producer, close the database pool, flush traces, exit 0.
 * If that takes longer than SHUTDOWN_TIMEOUT_SECONDS the process exits 1 so the platform's grace
 * period (ECS stopTimeout 30, Kubernetes terminationGracePeriodSeconds 30) is never the one that
 * kills it.
 */
import type { FastifyInstance } from 'fastify';

import type { Db } from './db.js';
import type { Publishers } from './publishers.js';

export interface ShutdownDeps {
  app: FastifyInstance;
  publishers: Publishers;
  db: Db;
  shutdownTelemetry: () => Promise<void>;
  timeoutSeconds: number;
}

export function installShutdownHandlers(deps: ShutdownDeps): void {
  let shuttingDown = false;

  const shutdown = async (signal: NodeJS.Signals): Promise<void> => {
    if (shuttingDown) return;
    shuttingDown = true;
    deps.app.log.info({ signal, timeout_seconds: deps.timeoutSeconds }, 'shutdown signal received');

    const deadline = setTimeout(() => {
      deps.app.log.error({ timeout_seconds: deps.timeoutSeconds }, 'shutdown deadline exceeded, exiting');
      process.exit(1);
    }, deps.timeoutSeconds * 1000);
    deadline.unref();

    try {
      await deps.app.close();
      await deps.publishers.close();
      await deps.db.end();
      await deps.shutdownTelemetry();
      deps.app.log.info('orders stopped');
      process.exit(0);
    } catch (err) {
      deps.app.log.error({ error: err instanceof Error ? err.message : String(err) }, 'shutdown failed');
      process.exit(1);
    }
  };

  process.once('SIGTERM', () => void shutdown('SIGTERM'));
  process.once('SIGINT', () => void shutdown('SIGINT'));
}
