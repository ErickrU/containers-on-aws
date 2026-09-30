// Telemetry first: it registers the ESM loader hook and starts the SDK before anything else loads.
import './telemetry.js';

// The application is loaded through a dynamic import so fastify, pg, undici, @aws-sdk and kafkajs
// are resolved after the hook above is in place; a static import would hoist them ahead of it.
const { main } = await import('./main.js');
await main();
