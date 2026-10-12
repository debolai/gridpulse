#!/bin/sh
# Bootstrap Lakekeeper and create the `gridpulse` warehouse. Idempotent: reruns are no-ops.
set -eu
API=http://lakekeeper:8181/management/v1

post() {
  # Prints the HTTP status; body goes to /tmp/body for error reporting.
  curl -s -o /tmp/body -w '%{http_code}' -X POST "$API/$1" -H 'Content-Type: application/json' --data "$2"
}

code=$(post bootstrap '{"accept-terms-of-use": true}')
case "$code" in
  2??) echo "lakekeeper: bootstrapped" ;;
  4??) echo "lakekeeper: already bootstrapped ($code)" ;;
  *) echo "lakekeeper bootstrap failed: $code"; cat /tmp/body; exit 1 ;;
esac

if curl -sf "$API/warehouse" | grep -q '"name":"gridpulse"'; then
  echo "warehouse gridpulse: already exists"
  exit 0
fi

code=$(post warehouse "@/init/warehouse.json")
case "$code" in
  2??) echo "warehouse gridpulse: created" ;;
  *) echo "warehouse create failed: $code"; cat /tmp/body; exit 1 ;;
esac
