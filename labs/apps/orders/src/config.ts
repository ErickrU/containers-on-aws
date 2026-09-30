/**
 * Configuration from the environment only (labs/CONTRACT.md §2).
 *
 * Unknown variables are ignored. Every problem is collected and reported at once as a ConfigError;
 * index.ts turns that into exit code 2 with the message on stderr.
 */

export class ConfigError extends Error {
  override readonly name = 'ConfigError';
}

export const LOG_LEVELS = ['debug', 'info', 'warn', 'error'] as const;
export type LogLevel = (typeof LOG_LEVELS)[number];

export interface Config {
  port: number;
  databaseUrl: string;
  catalogUrl: string;
  sqsQueueUrl: string;
  awsRegion: string;
  /** Local only (ElasticMQ): the standard SDK variable AWS_ENDPOINT_URL_SQS. */
  awsEndpointUrlSqs?: string;
  /** Empty when KAFKA_BROKERS is unset: the Kafka event is skipped. */
  kafkaBrokers: string[];
  kafkaTopic: string;
  /** Undefined when OTEL_EXPORTER_OTLP_ENDPOINT is unset: tracing is disabled. */
  otlpEndpoint?: string;
  serviceName: string;
  logLevel: LogLevel;
  shutdownTimeoutSeconds: number;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const errors: string[] = [];
  const get = (name: string): string | undefined => {
    const value = env[name]?.trim();
    return value ? value : undefined;
  };
  const required = (name: string, example: string): string => {
    const value = get(name);
    if (!value) {
      errors.push(`${name} is required, for example ${example}`);
      return '';
    }
    return value;
  };
  const positiveInt = (name: string, fallback: number, max = Number.MAX_SAFE_INTEGER): number => {
    const raw = get(name);
    if (raw === undefined) return fallback;
    const n = Number(raw);
    if (!Number.isInteger(n) || n < 1 || n > max) {
      errors.push(`${name} must be an integer between 1 and ${max}, got "${raw}"`);
      return fallback;
    }
    return n;
  };

  const databaseUrl = required('DATABASE_URL', 'postgres://app:app@postgres:5432/shopfront');
  const catalogUrl = required('CATALOG_URL', 'http://catalog:8081').replace(/\/+$/, '');
  const sqsQueueUrl = required('SQS_QUEUE_URL', 'http://elasticmq:9324/000000000000/orders-created');
  const awsRegion = required('AWS_REGION', 'us-east-1');

  const port = positiveInt('PORT', 8080, 65535);
  const shutdownTimeoutSeconds = positiveInt('SHUTDOWN_TIMEOUT_SECONDS', 20);

  const kafkaBrokers = (get('KAFKA_BROKERS') ?? '')
    .split(',')
    .map((b) => b.trim())
    .filter(Boolean);

  if ((get('KAFKA_SASL_IAM') ?? 'false').toLowerCase() === 'true') {
    errors.push('KAFKA_SASL_IAM=true is not supported by this service yet; unset it or use a plaintext listener');
  }

  const rawLevel = (get('LOG_LEVEL') ?? 'info').toLowerCase();
  const logLevel = (LOG_LEVELS as readonly string[]).includes(rawLevel) ? (rawLevel as LogLevel) : 'info';
  if (logLevel !== rawLevel) {
    errors.push(`LOG_LEVEL must be one of ${LOG_LEVELS.join(', ')}, got "${rawLevel}"`);
  }

  if (errors.length > 0) {
    throw new ConfigError(errors.join('; '));
  }

  return {
    port,
    databaseUrl,
    catalogUrl,
    sqsQueueUrl,
    awsRegion,
    awsEndpointUrlSqs: get('AWS_ENDPOINT_URL_SQS'),
    kafkaBrokers,
    kafkaTopic: get('KAFKA_TOPIC') ?? 'orders.created',
    otlpEndpoint: get('OTEL_EXPORTER_OTLP_ENDPOINT'),
    serviceName: get('OTEL_SERVICE_NAME') ?? 'orders',
    logLevel,
    shutdownTimeoutSeconds,
  };
}

/** Safe to log: the password part of a URL is replaced, unparsable values are hidden entirely. */
export function redactUrl(raw: string): string {
  try {
    const url = new URL(raw);
    if (url.password) url.password = 'xxxxx';
    return url.toString();
  } catch {
    return '<redacted>';
  }
}
