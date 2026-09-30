/**
 * Publishing the order.created event (labs/CONTRACT.md §5).
 *
 * SQS is the critical path: the fulfillment worker only sees orders that reach the queue, so a
 * failed SendMessage is an error the route reports (500; the order row exists with status CREATED).
 * Kafka feeds analytics and is best effort: a failed produce is logged, never surfaced.
 *
 * Trace context travels as the W3C traceparent (and tracestate) in SQS message attributes and Kafka
 * record headers, injected from the active OpenTelemetry context; the consumers extract it.
 */
import type { SendMessageCommandInput } from '@aws-sdk/client-sqs';
import { context as otelContext, propagation, type Context } from '@opentelemetry/api';
import type { FastifyBaseLogger } from 'fastify';
import { Kafka, Partitioners, logLevel as kafkaLogLevel, type Producer, type logCreator } from 'kafkajs';

import type { Order } from './db.js';

export interface OrderCreatedEvent {
  type: 'order.created';
  version: 1;
  orderId: string;
  productId: number;
  quantity: number;
  priceCents: number;
  createdAt: string;
}

export function orderCreatedEvent(order: Order): OrderCreatedEvent {
  return {
    type: 'order.created',
    version: 1,
    orderId: order.id,
    productId: order.productId,
    quantity: order.quantity,
    priceCents: order.priceCents,
    createdAt: order.createdAt,
  };
}

/** W3C trace context of ctx as a flat map: {traceparent, tracestate?}. Empty without an active span. */
export function traceCarrier(ctx: Context = otelContext.active()): Record<string, string> {
  const carrier: Record<string, string> = {};
  propagation.inject(ctx, carrier);
  return carrier;
}

export interface EventPublisher {
  publish(event: OrderCreatedEvent, ctx?: Context): Promise<void>;
  /** Optional start-up connection; must never reject. */
  warmUp?(): Promise<void>;
  close(): Promise<void>;
}

/** The one SDK call the SQS publisher needs; production passes `(input) => sqs.send(new SendMessageCommand(input))`. */
export type SendMessageFn = (input: SendMessageCommandInput) => Promise<unknown>;

export class SqsPublisher implements EventPublisher {
  constructor(
    private readonly sendMessage: SendMessageFn,
    private readonly queueUrl: string,
  ) {}

  async publish(event: OrderCreatedEvent, ctx: Context = otelContext.active()): Promise<void> {
    const attributes = Object.fromEntries(
      Object.entries(traceCarrier(ctx)).map(([name, value]) => [name, { DataType: 'String', StringValue: value }]),
    );
    await this.sendMessage({
      QueueUrl: this.queueUrl,
      MessageBody: JSON.stringify(event),
      MessageAttributes: attributes,
    });
  }

  async close(): Promise<void> {
    // the SQS client holds no long-lived connection worth draining
  }
}

export interface KafkaPublisherOptions {
  brokers: string[];
  topic: string;
  clientId?: string;
  logger: FastifyBaseLogger;
}

/** kafkajs logs through our pino logger so every line on stdout keeps the same JSON shape. */
function pinoLogCreator(logger: FastifyBaseLogger): logCreator {
  return () =>
    ({ namespace, level, log }) => {
      const { message, timestamp: _timestamp, ...rest } = log;
      const fields = { ...rest, kafka_namespace: namespace };
      if (level === kafkaLogLevel.ERROR) logger.error(fields, message);
      else if (level === kafkaLogLevel.WARN) logger.warn(fields, message);
      else if (level === kafkaLogLevel.INFO) logger.info(fields, message);
      else logger.debug(fields, message);
    };
}

export class KafkaPublisher implements EventPublisher {
  private readonly kafka: Kafka;
  private readonly producer: Producer;
  private readonly topic: string;
  private readonly logger: FastifyBaseLogger;
  private connecting: Promise<void> | undefined;

  constructor(options: KafkaPublisherOptions) {
    this.topic = options.topic;
    this.logger = options.logger;
    this.kafka = new Kafka({
      clientId: options.clientId ?? 'orders',
      brokers: options.brokers,
      connectionTimeout: 2_000,
      retry: { retries: 2, initialRetryTime: 200 },
      logLevel: kafkaLogLevel.WARN,
      logCreator: pinoLogCreator(options.logger),
    });
    this.producer = this.kafka.producer({
      allowAutoTopicCreation: true,
      // explicit choice of the (murmur2, Java-compatible) default silences the kafkajs 2.0 warning
      createPartitioner: Partitioners.DefaultPartitioner,
    });
  }

  /** Connects once; a failed attempt is forgotten so the next publish tries again. */
  private ensureConnected(): Promise<void> {
    this.connecting ??= this.connect().catch((err: unknown) => {
      this.connecting = undefined;
      throw err;
    });
    return this.connecting;
  }

  private async connect(): Promise<void> {
    await this.producer.connect();
    // Broker-side auto-creation happens on the first metadata request, and the very first produce
    // races it ("does not host this topic-partition", retried by kafkajs but logged as an error).
    // Creating a missing topic up front and waiting for its leaders avoids that. Without permission
    // to create topics the produce path still works through auto-creation.
    const admin = this.kafka.admin();
    try {
      await admin.connect();
      if ((await admin.listTopics()).includes(this.topic)) {
        this.logger.debug({ topic: this.topic }, 'kafka topic exists');
        return;
      }
      await admin.createTopics({
        waitForLeaders: true,
        topics: [{ topic: this.topic, numPartitions: 3, replicationFactor: -1 }],
      });
      this.logger.info({ topic: this.topic, partitions: 3 }, 'kafka topic created');
    } catch (err) {
      this.logger.warn(
        { topic: this.topic, error: err instanceof Error ? err.message : String(err) },
        'could not ensure the kafka topic exists; relying on broker auto-creation',
      );
    } finally {
      await admin.disconnect().catch(() => undefined);
    }
  }

  /** Connects at start-up so the first order does not pay for the connection; failures are logged. */
  async warmUp(): Promise<void> {
    try {
      await this.ensureConnected();
      this.logger.info({ topic: this.topic }, 'kafka producer connected');
    } catch (err) {
      this.logger.warn(
        { error: err instanceof Error ? err.message : String(err) },
        'kafka producer not connected yet; will retry on the first order',
      );
    }
  }

  async publish(event: OrderCreatedEvent, ctx: Context = otelContext.active()): Promise<void> {
    await this.ensureConnected();
    await this.producer.send({
      topic: this.topic,
      timeout: 3_000,
      messages: [{ key: event.orderId, value: JSON.stringify(event), headers: traceCarrier(ctx) }],
    });
  }

  async close(): Promise<void> {
    await this.producer.disconnect();
  }
}

export interface Publishers {
  /** Sends the SQS message (rejects on failure), then produces the Kafka event (failures are logged). */
  publishOrderCreated(event: OrderCreatedEvent, ctx?: Context): Promise<void>;
  /** Best-effort start-up connections; never rejects. */
  warmUp(): Promise<void>;
  close(): Promise<void>;
}

export function createPublishers(deps: {
  sqs: EventPublisher;
  kafka?: EventPublisher;
  logger: FastifyBaseLogger;
}): Publishers {
  return {
    async warmUp() {
      await Promise.allSettled([deps.sqs.warmUp?.(), deps.kafka?.warmUp?.()]);
    },
    async publishOrderCreated(event, ctx = otelContext.active()) {
      await deps.sqs.publish(event, ctx);
      if (!deps.kafka) return;
      try {
        await deps.kafka.publish(event, ctx);
      } catch (err) {
        deps.logger.error(
          { order_id: event.orderId, error: err instanceof Error ? err.message : String(err) },
          'kafka produce failed; the order is queued on SQS, analytics will miss this event',
        );
      }
    },
    async close() {
      await Promise.allSettled([deps.sqs.close(), deps.kafka?.close()]);
    },
  };
}
