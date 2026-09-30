/**
 * OpenTelemetry for the orders service (labs/CONTRACT.md §6).
 *
 * Enabled only when OTEL_EXPORTER_OTLP_ENDPOINT is set; without it the process runs with the no-op
 * API, spans cost nothing and log lines carry no trace_id. The OTLP exporter reads the endpoint
 * from the environment itself and appends /v1/traces, like the Go and Python SDKs do.
 *
 * ESM caveat: the auto-instrumentations patch modules while they are loaded. index.ts imports this
 * file first and then loads the rest of the application through a dynamic import, so the loader
 * hook registered here is in place before fastify, pg, undici (fetch), @aws-sdk and kafkajs load.
 */
import { register } from 'node:module';

import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { resourceFromAttributes } from '@opentelemetry/resources';
import { NodeSDK } from '@opentelemetry/sdk-node';
import { ATTR_SERVICE_NAME } from '@opentelemetry/semantic-conventions';

const endpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT?.trim();
let sdk: NodeSDK | undefined;

if (endpoint) {
  register('@opentelemetry/instrumentation/hook.mjs', import.meta.url);

  sdk = new NodeSDK({
    // OTEL_RESOURCE_ATTRIBUTES (deployment.environment=...) is merged in by the default detectors.
    resource: resourceFromAttributes({ [ATTR_SERVICE_NAME]: process.env.OTEL_SERVICE_NAME?.trim() || 'orders' }),
    traceExporter: new OTLPTraceExporter(),
    instrumentations: [
      getNodeAutoInstrumentations({
        // very chatty, no value for this service
        '@opentelemetry/instrumentation-fs': { enabled: false },
        '@opentelemetry/instrumentation-dns': { enabled: false },
        '@opentelemetry/instrumentation-net': { enabled: false },
        '@opentelemetry/instrumentation-http': {
          ignoreIncomingRequestHook: (request) =>
            request.url === '/healthz' || request.url === '/readyz' || request.url === '/metrics',
        },
      }),
    ],
  });
  sdk.start();
}

export const tracingEnabled = Boolean(endpoint);

/** Flushes queued spans and stops the exporter; a no-op when tracing is disabled. */
export async function shutdownTelemetry(): Promise<void> {
  await sdk?.shutdown();
}
