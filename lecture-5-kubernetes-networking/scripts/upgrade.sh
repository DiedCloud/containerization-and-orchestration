#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
helm upgrade --install shop ./shop --kube-context kind-lab2 -n shop \
  --reset-values "$@"
