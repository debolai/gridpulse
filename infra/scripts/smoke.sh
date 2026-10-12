#!/usr/bin/env bash
# Post-deploy smoke test: services are healthy, and one known metric served by the semantic API
# equals an independent Athena query. If Bedrock is usable, the assistant answers one question.
source "$(dirname "$0")/aws-common.sh"
PORT=18090
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" port-forward svc/semantic-api "$PORT:8090" >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do curl -sf "http://localhost:$PORT/health" >/dev/null && break; sleep 2; done
echo "semantic-api /health: $(curl -sf "http://localhost:$PORT/health")"

api=$(curl -sf -X POST "http://localhost:$PORT/query" -H 'Content-Type: application/json' -d '{
  "metrics": ["demand"],
  "filters": [{"dimension": "balancing_authority", "values": ["PJM"]}],
  "start": "2026-07-01T00:00:00Z", "end": "2026-08-01T00:00:00Z"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["rows"][0][0])')

qid=$(aws athena start-query-execution --work-group "gridpulse-$ENV_NAME" --query QueryExecutionId --output text \
  --query-string "SELECT sum(demand_mwh) FROM marts.fct_grid_hourly WHERE ba_code = 'PJM' AND period_utc >= TIMESTAMP '2026-07-01 00:00:00' AND period_utc < TIMESTAMP '2026-08-01 00:00:00'")
while state=$(aws athena get-query-execution --query-execution-id "$qid" --query QueryExecution.Status.State --output text); [ "$state" = RUNNING ] || [ "$state" = QUEUED ]; do sleep 1; done
ref=$(aws athena get-query-results --query-execution-id "$qid" --query 'ResultSet.Rows[1].Data[0].VarCharValue' --output text)

python3 - "$api" "$ref" <<'PY'
import math, sys
api, ref = float(sys.argv[1]), float(sys.argv[2])
ok = math.isclose(api, ref, rel_tol=1e-9)
print(f"PJM demand, July 2026: semantic API {api:,.0f} vs Athena {ref:,.0f} -> {'MATCH' if ok else 'MISMATCH'}")
sys.exit(0 if ok else 1)
PY

kill $PF 2>/dev/null || true
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" port-forward svc/agent-api 18091:8091 >/dev/null 2>&1 &
PF=$!
for _ in $(seq 1 30); do curl -sf "http://localhost:18091/health" >/dev/null && break; sleep 2; done
echo "agent-api /health: $(curl -sf http://localhost:18091/health)"
answer=$(curl -s -X POST http://localhost:18091/ask -H 'Content-Type: application/json' \
  -d '{"question": "What was PJM total demand in July 2026?"}' --max-time 120 || true)
if echo "$answer" | grep -q '"status":"answered"'; then
  echo "assistant: answered (numbers verified)"
else
  echo "assistant: no verified answer yet (Bedrock access pending? see TODO #11). Response: ${answer:0:200}"
fi
