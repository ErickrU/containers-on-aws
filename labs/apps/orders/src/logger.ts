/**
 * JSON logging, one object per line on stdout (labs/CONTRACT.md §6): time, level, msg, service and,
 * while a span is active, trace_id and span_id. The same pino instance is handed to Fastify
 * (loggerInstance), to the publishers and to the shutdown handler, so every line has one shape.
 */
import { isSpanContextValid, trace } from '@opentelemetry/api';
import { pino, type Logger, type LoggerOptions } from 'pino';

import type { LogLevel } from './config.js';

export type AppLogger = Logger;

export function loggerOptions(level: LogLevel, service: string): LoggerOptions {
  return {
    level,
    // base replaces pino's default pid/hostname with the field the contract asks for
    base: { service },
    messageKey: 'msg',
    timestamp: () => `,"time":"${new Date().toISOString()}"`,
    formatters: {
      // "info" instead of 30: the same vocabulary as LOG_LEVEL across every shopfront service
      level: (label) => ({ level: label }),
    },
    mixin: () => {
      const spanContext = trace.getActiveSpan()?.spanContext();
      return spanContext && isSpanContextValid(spanContext)
        ? { trace_id: spanContext.traceId, span_id: spanContext.spanId }
        : {};
    },
    // never log full request bodies or headers (which may carry credentials)
    serializers: {
      req: (req: { method: string; url: string }) => ({ method: req.method, url: req.url }),
      res: (res: { statusCode: number }) => ({ status: res.statusCode }),
    },
  };
}

export function createLogger(level: LogLevel, service: string): AppLogger {
  return pino(loggerOptions(level, service));
}
