#!/usr/bin/env bash
set -euo pipefail
lab_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "$lab_dir/scripts/node-resources.py" --node lab2-control-plane --reserved-cpu 12
python3 "$lab_dir/scripts/node-resources.py" --node lab2-worker --reserved-cpu 14
