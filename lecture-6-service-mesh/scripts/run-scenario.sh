#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
name="${1:?bad or good}"
case "$name" in
  bad) fail=true; duration=145 ;;
  good) fail=false; duration=210 ;;
  *) exit 2 ;;
esac
kubectl -n shop6 delete job shop-gate --ignore-not-found --wait=true
bash scripts/upgrade.sh --set mesh.enabled=true --set api.v2.replicas=1 \
  --set api.v2.fail="$fail" --set api.v1.flaky=false --set traffic.retries=false \
  --set traffic.v2Weight=10 --set monitoring.enabled=true --set gate.enabled=true --wait --timeout 3m
kubectl -n shop6 exec -i deploy/shop-client -c client -- python - --seconds "$duration" < scripts/load.py > "/tmp/lab6-$name-load.jsonl" &
load_pid=$!
python3 scripts/scenario.py "$name"
wait "$load_pid"
python3 scripts/plot.py "$name"
