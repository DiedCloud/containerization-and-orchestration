#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
helm upgrade --install shop ./shop -n shop6 --create-namespace "$@"
