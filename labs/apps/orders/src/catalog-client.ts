/**
 * HTTP client for the catalog service (labs/CONTRACT.md §3): GET {CATALOG_URL}/products/{id} with a
 * 2 s timeout and one retry on 5xx or timeout. Uses the global fetch (undici), which the
 * OpenTelemetry undici instrumentation traces and decorates with the traceparent header.
 */

export interface Product {
  id: number;
  sku: string;
  name: string;
  price_cents: number;
  stock: number;
}

export interface CatalogClient {
  /** Resolves null when the catalog answers 404. */
  getProduct(id: number): Promise<Product | null>;
}

/** The catalog did not give a usable answer after the retry; POST /orders turns this into 502. */
export class CatalogUnavailableError extends Error {
  override readonly name = 'CatalogUnavailableError';
}

export interface CatalogClientOptions {
  timeoutMs?: number;
  attempts?: number;
  fetchImpl?: typeof fetch;
}

const isProduct = (value: unknown): value is Product => {
  const p = value as Partial<Product> | null;
  return (
    typeof p === 'object' &&
    p !== null &&
    typeof p.id === 'number' &&
    typeof p.price_cents === 'number' &&
    typeof p.stock === 'number'
  );
};

export function createCatalogClient(baseUrl: string, options: CatalogClientOptions = {}): CatalogClient {
  const timeoutMs = options.timeoutMs ?? 2_000;
  const attempts = options.attempts ?? 2; // first try plus one retry
  const fetchImpl = options.fetchImpl ?? fetch;
  const base = baseUrl.replace(/\/+$/, '');

  return {
    async getProduct(id: number): Promise<Product | null> {
      const url = `${base}/products/${id}`;
      let lastFailure = 'no attempt made';

      for (let attempt = 1; attempt <= attempts; attempt++) {
        let response: Response;
        try {
          response = await fetchImpl(url, {
            headers: { accept: 'application/json' },
            signal: AbortSignal.timeout(timeoutMs),
          });
        } catch (err) {
          // timeout (TimeoutError) or connection failure: retry
          lastFailure = err instanceof Error ? `${err.name}: ${err.message}` : String(err);
          continue;
        }

        if (response.status === 404) return null;
        if (response.status >= 500) {
          lastFailure = `catalog answered HTTP ${response.status}`;
          continue; // retry once on 5xx
        }
        if (!response.ok) {
          throw new CatalogUnavailableError(`catalog answered HTTP ${response.status} for ${url}`);
        }

        const body: unknown = await response.json();
        if (!isProduct(body)) {
          throw new CatalogUnavailableError(`catalog returned an unexpected body for ${url}`);
        }
        return body;
      }

      throw new CatalogUnavailableError(`catalog unavailable after ${attempts} attempts: ${lastFailure}`);
    },
  };
}
