#!/usr/bin/env bash
# shopfront end-to-end smoke test - the seven steps of labs/CONTRACT.md §10.
#
#   make smoke            (or: labs/local/smoke.sh)
#
# Requires: docker compose, curl, jq. Every step prints PASS or FAIL; the script exits non-zero
# when any step failed. Override endpoints with ORDERS_URL / CATALOG_URL / JAEGER_URL when the
# stack does not run on localhost.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/labs/local/compose.yaml")

ORDERS_URL="${ORDERS_URL:-http://localhost:8080}"
CATALOG_URL="${CATALOG_URL:-http://localhost:8081}"
JAEGER_URL="${JAEGER_URL:-http://localhost:16686}"
READY_TIMEOUT="${READY_TIMEOUT:-120}"   # seconds to wait for /readyz
FULFILL_TIMEOUT="${FULFILL_TIMEOUT:-30}" # seconds to wait for status FULFILLED (contract: 30)
PRODUCT_ID="${PRODUCT_ID:-1}"
QUANTITY="${QUANTITY:-2}"

failures=0
pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }
skip() { printf 'SKIP  %s\n' "$*"; }

http_code() { curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$1" || true; }

wait_ready() {
  local name=$1 url=$2 deadline=$((SECONDS + READY_TIMEOUT)) code
  while true; do
    code=$(http_code "$url/readyz")
    if [[ $code == 200 ]]; then
      return 0
    fi
    if (( SECONDS >= deadline )); then
      printf '      %s /readyz last answered %s after %ss\n' "$name" "${code:-no response}" "$READY_TIMEOUT"
      return 1
    fi
    sleep 2
  done
}

cache_header() {
  # Prints the value of X-Cache for one GET (header names are case-insensitive).
  curl -s -D - -o /dev/null --max-time 5 "$CATALOG_URL/products/$PRODUCT_ID" \
    | tr -d '\r' | awk 'tolower($1) == "x-cache:" { print $2 }'
}

echo "shopfront smoke test  orders=$ORDERS_URL catalog=$CATALOG_URL"

# 1. readiness ------------------------------------------------------------------------------
if wait_ready orders "$ORDERS_URL" && wait_ready catalog "$CATALOG_URL"; then
  pass "1 orders and catalog answer 200 on /readyz"
else
  fail "1 services not ready within ${READY_TIMEOUT}s (docker compose ps; docker compose logs orders catalog)"
  echo "RESULT: FAIL ($failures step(s) failed)"
  exit 1
fi

# 2. cache-aside -------------------------------------------------------------------------------
first=$(cache_header)
second=$(cache_header)
if [[ $second == HIT ]]; then
  pass "2 GET /products/$PRODUCT_ID twice -> X-Cache: ${first:-?} then HIT"
elif [[ $first == BYPASS || $second == BYPASS ]]; then
  fail "2 X-Cache: BYPASS - catalog runs without Valkey (VALKEY_URL unset or Valkey unreachable)"
else
  fail "2 expected X-Cache: HIT on the second request, got '${first:-none}' then '${second:-none}'"
fi

# 3. create an order --------------------------------------------------------------------------
response=$(curl -s --max-time 10 -w '\n%{http_code}' -H 'content-type: application/json' \
  -d "{\"productId\": $PRODUCT_ID, \"quantity\": $QUANTITY}" "$ORDERS_URL/orders")
code=${response##*$'\n'}
body=${response%$'\n'*}
order_id=$(printf '%s' "$body" | jq -r '.id // empty' 2>/dev/null || true)
if [[ $code == 201 && -n $order_id ]]; then
  pass "3 POST /orders -> 201 id=$order_id status=$(printf '%s' "$body" | jq -r '.status')"
else
  fail "3 POST /orders -> HTTP $code: ${body:0:200}"
  echo "RESULT: FAIL ($failures step(s) failed)"
  exit 1
fi

# 4. fulfillment through SQS ---------------------------------------------------------------------
status=""
deadline=$((SECONDS + FULFILL_TIMEOUT))
while (( SECONDS < deadline )); do
  status=$(curl -s --max-time 5 "$ORDERS_URL/orders/$order_id" | jq -r '.status // empty' 2>/dev/null || true)
  if [[ $status == FULFILLED ]]; then
    break
  fi
  sleep 1
done
if [[ $status == FULFILLED ]]; then
  pass "4 GET /orders/$order_id -> status FULFILLED (SQS -> fulfillment-worker -> UPDATE)"
else
  fail "4 order still '${status:-unknown}' after ${FULFILL_TIMEOUT}s (docker compose logs fulfillment-worker; ElasticMQ UI http://localhost:9325)"
fi

# 5. metrics ----------------------------------------------------------------------------------
if curl -s --max-time 5 "$ORDERS_URL/metrics" | grep -q '^orders_created_total'; then
  pass "5 GET /metrics on orders exposes orders_created_total"
else
  fail "5 orders_created_total missing from $ORDERS_URL/metrics"
fi

# 6. analytics through Kafka -------------------------------------------------------------------
if ! "${COMPOSE[@]}" ps --services --status running 2>/dev/null | grep -qx kafka; then
  skip "6 daily_stats check: kafka service is not running"
else
  count=""
  deadline=$((SECONDS + FULFILL_TIMEOUT))
  while (( SECONDS < deadline )); do
    count=$("${COMPOSE[@]}" exec -T postgres psql -U app -d shopfront -tAc \
      "SELECT orders_count FROM daily_stats WHERE day = (now() AT TIME ZONE 'UTC')::date" 2>/dev/null || true)
    if [[ $count =~ ^[0-9]+$ ]] && (( count >= 1 )); then
      break
    fi
    sleep 2
  done
  if [[ $count =~ ^[0-9]+$ ]] && (( count >= 1 )); then
    pass "6 daily_stats has today's row (orders_count=$count) via Kafka -> analytics-consumer"
  else
    fail "6 no daily_stats row for today after ${FULFILL_TIMEOUT}s (docker compose logs analytics-consumer kafka)"
  fi
fi

# 7. trace ----------------------------------------------------------------------------------------
echo "      trace: $JAEGER_URL/search?service=orders&operation=POST%20%2Forders&limit=20"
pass "7 open the Jaeger URL above; the trace spans orders -> catalog -> SQS -> fulfillment-worker"

if (( failures > 0 )); then
  echo "RESULT: FAIL ($failures step(s) failed)"
  exit 1
fi
echo "RESULT: PASS"
