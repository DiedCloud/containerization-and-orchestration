#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p results
kubectl -n shop rollout status deployment/shop-api --timeout=2m
kubectl -n shop rollout status deployment/shop-worker --timeout=2m
# Docker's local DNS resolves the node name; no public wildcard DNS dependency.
docker run --rm --network kind -i docker.io/library/shop:1.1.0 \
  python - --url http://lab2-control-plane:30080 --duration 180 \
  < scripts/load.py > results/client.jsonl &
external_pid=$!
kubectl -n shop exec -i deployment/shop-client -- python - --duration 180 \
  < scripts/load.py > results/internal-client.jsonl &
internal_pid=$!
python3 scripts/chaos.py --duration 180 > results/chaos.log &
chaos_pid=$!
trap 'kill "$external_pid" "$internal_pid" "$chaos_pid" 2>/dev/null || true' EXIT
wait "$external_pid"
wait "$internal_pid"
wait "$chaos_pid"
python3 scripts/plot-chaos.py --output results/chaos.png
