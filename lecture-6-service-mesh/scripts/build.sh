#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t shop:6.0.0 services
docker build -t shop-gate:6.0.0 gate
kind load docker-image shop:6.0.0 shop-gate:6.0.0 --name lab2
