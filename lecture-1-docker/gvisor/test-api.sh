#!/bin/sh
set -eu

# The same script is the OCI launcher on the host and the health probe inside.
if [ "${1:-}" = --inside ]; then
    /app/api &
    API_PID=$!
    trap 'kill "$API_PID" 2>/dev/null || true; wait "$API_PID" 2>/dev/null || true' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    attempt=0
    while [ "$attempt" -lt 50 ]; do
        kill -0 "$API_PID"
        if wget -qO- http://127.0.0.1:8080/health 2>/dev/null; then
            uname -a
            exit 0
        fi
        attempt=$((attempt + 1))
        sleep 0.1
    done
    exit 1
fi

RUNSC=${RUNSC:-runsc}
IMAGE=${1:-myapi:multi}
BUNDLE=$(mktemp -d)
CONTAINER=""
cleanup() {
    if [ -n "$CONTAINER" ]; then docker rm "$CONTAINER" >/dev/null 2>&1 || true; fi
    "$RUNSC" --root "$BUNDLE/state" delete --force lab1 >/dev/null 2>&1 || true
    rm -rf -- "$BUNDLE"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir "$BUNDLE/rootfs"
CONTAINER=$(docker create "$IMAGE")
docker export "$CONTAINER" -o "$BUNDLE/rootfs.tar"
tar --no-same-owner -xf "$BUNDLE/rootfs.tar" -C "$BUNDLE/rootfs"
cp "$0" "$BUNDLE/rootfs/test-api.sh"
"$RUNSC" spec --bundle "$BUNDLE" --cwd /app -- /bin/sh /test-api.sh --inside
python3 - "$BUNDLE/config.json" <<'PY'
import json
import os
import sys

path = sys.argv[1]
with open(path) as source:
    spec = json.load(source)
# A single UID mapping permits an unprivileged run without installing a daemon.
spec["linux"]["namespaces"] = [n for n in spec["linux"]["namespaces"] if n["type"] != "network"]
spec["linux"]["namespaces"].append({"type": "user"})
spec["linux"]["uidMappings"] = [{"containerID": 0, "hostID": os.getuid(), "size": 1}]
spec["linux"]["gidMappings"] = [{"containerID": 0, "hostID": os.getgid(), "size": 1}]
with open(path, "w") as target:
    json.dump(spec, target)
PY
"$RUNSC" --root "$BUNDLE/state" --platform=systrap --network=none \
    --ignore-cgroups run --bundle "$BUNDLE" lab1
