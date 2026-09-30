/**
 * Process bootstrap (labs/CONTRACT.md §7): validate config -> build the app -> wait for the database
 * (backoff, 30 s) -> listen -> mark ready. Exit codes: 0 clean, 1 runtime error, 2 configuration error.
 */
import { SQSClient, SendMessageCommand } from '@aws-sdk/client-sqs';

import { buildApp } from './app.js';
import { createCatalogClient } from './catalog-client.js';
import { ConfigError, loadConfig, redactUrl, type Config } from './config.js';
import { createDb, waitForDatabase } from './db.js';
import { createLogger } from './logger.js';
import { createMetrics } from './metrics.js';
import { KafkaPublisher, SqsPublisher, createPublishers } from './publishers.js';
import { installShutdownHandlers } from './shutdown.js';
import { shutdownTelemetry, tracingEnabled } from './telemetry.js';

const EXIT_RUNTIME_ERROR = 1;
const EXIT_CONFIG_ERROR = 2;

export async function main(): Promise<void> {
  let config: Config;
  try {
    config = loadConfig();
  } catch (err) {
    if (err instanceof ConfigError) {
      process.stderr.write(`configuration error: ${err.message}\n`);
      process.exit(EXIT_CONFIG_ERROR);
    }
    throw err;
  }

  const logger = createLogger(config.logLevel, config.serviceName);
  logger.info(
    {
      port: config.port,
      database_url: redactUrl(config.databaseUrl),
      catalog_url: config.catalogUrl,
      sqs_queue_url: config.sqsQueueUrl,
      aws_region: config.awsRegion,
      kafka_brokers: config.kafkaBrokers,
      kafka_topic: config.kafkaBrokers.length > 0 ? config.kafkaTopic : null,
      tracing: tracingEnabled ? config.otlpEndpoint : 'disabled',
      shutdown_timeout_seconds: config.shutdownTimeoutSeconds,
    },
    'starting orders',
  );

  const db = createDb(config.databaseUrl);
  db.onIdleClientError((err) => logger.warn({ error: err.message }, 'idle database client error'));

  // Region comes from the contract's AWS_REGION; AWS_ENDPOINT_URL_SQS points at ElasticMQ locally.
  // Credentials come from the default provider chain (task role on ECS, Pod Identity on EKS).
  const sqs = new SQSClient({
    region: config.awsRegion,
    ...(config.awsEndpointUrlSqs ? { endpoint: config.awsEndpointUrlSqs } : {}),
  });
  const publishers = createPublishers({
    sqs: new SqsPublisher((input) => sqs.send(new SendMessageCommand(input)), config.sqsQueueUrl),
    kafka:
      config.kafkaBrokers.length > 0
        ? new KafkaPublisher({ brokers: config.kafkaBrokers, topic: config.kafkaTopic, logger })
        : undefined,
    logger,
  });

  const app = buildApp({
    db,
    catalog: createCatalogClient(config.catalogUrl),
    publishers,
    metrics: createMetrics(),
    logger,
  });

  try {
    await waitForDatabase(db, logger, 30_000);
  } catch (err) {
    logger.error({ error: err instanceof Error ? err.message : String(err) }, 'giving up on the database');
    await shutdownTelemetry();
    process.exit(EXIT_RUNTIME_ERROR);
  }

  installShutdownHandlers({
    app,
    publishers,
    db,
    shutdownTelemetry,
    timeoutSeconds: config.shutdownTimeoutSeconds,
  });

  // Not awaited: Kafka is best effort and must not delay readiness (the SQS path needs no warm-up).
  void publishers.warmUp();

  try {
    await app.listen({ port: config.port, host: '0.0.0.0' });
    logger.info({ port: config.port }, 'orders ready');
  } catch (err) {
    logger.error({ error: err instanceof Error ? err.message : String(err) }, 'listen failed');
    await shutdownTelemetry();
    process.exit(EXIT_RUNTIME_ERROR);
  }
}
