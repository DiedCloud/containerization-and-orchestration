"""Delete one operator-managed PostgreSQL Pod and verify recovery/data retention.

Detailed evidence is local and ignored by Git. Only the Pod is deleted.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.request


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--context", default="kind-lab2")
parser.add_argument("--url", default="http://172.20.0.2:30080")
parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts.local/03-postgres")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
log = []


def emit(message):
    print(message, flush=True)
    log.append(message)
    (args.output / "summary.txt").write_text("\n".join(log) + "\n")


def kube(*params):
    return subprocess.check_output(
        ["kubectl", "--context", args.context, "--request-timeout=15s", "-n", "shop", *params], text=True, timeout=20)


def get(kind, name):
    return json.loads(kube("get", kind, name, "-o", "json"))


def request(path, data=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(args.url.rstrip("/") + path,
                                 data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def ready(obj):
    return any(c["type"] == "Ready" and c["status"] == "True"
               for c in obj.get("status", {}).get("conditions", []))


cluster = get("cluster", "shop-postgres")
assert cluster["spec"]["instances"] == 1 and ready(cluster)
pod_name = cluster["status"]["currentPrimary"]
before = get("pod", pod_name)
assert ready(before)
assert any(o["kind"] == "Cluster" and o["uid"] == cluster["metadata"]["uid"] and o.get("controller")
           for o in before["metadata"]["ownerReferences"])
claim = next(v["persistentVolumeClaim"]["claimName"] for v in before["spec"]["volumes"] if v["name"] == "pgdata")
pvc_before = get("pvc", claim)
code, body = request("/orders")
assert code == 200
orders_before = json.loads(body)
emit("POSTGRES RECOVERY / CloudNativePG")
emit(f"Before: Pod={pod_name}, UID={before['metadata']['uid']}")
emit(f"Owner: Cluster/{cluster['metadata']['name']}, UID={cluster['metadata']['uid']}")
emit(f"PVC={claim}, UID={pvc_before['metadata']['uid']}, PV={pvc_before['spec']['volumeName']}")
emit(f"Orders before deletion: {len(orders_before)}")
(args.output / "cluster-before.yaml").write_text(kube("get", "cluster", "shop-postgres", "-o", "yaml"))
stop = threading.Event()
samples = []
start = time.monotonic()


def probe(path):
    while not stop.is_set():
        row = {"utc": datetime.now(timezone.utc).isoformat(), "elapsed": round(time.monotonic() - start, 3),
               "path": path, "status": 0, "error": ""}
        try:
            row["status"], _ = request(path)
        except Exception as exc:
            row["error"] = str(exc)
        samples.append(row)
        stop.wait(0.2)


threads = [threading.Thread(target=probe, args=(path,)) for path in ["/health", "/orders"]]
for thread in threads:
    thread.start()
try:
    time.sleep(1)
    deletion_start = time.monotonic()
    emit(kube("delete", "pod", pod_name, "--wait=false").strip())
    deadline = time.monotonic() + 180
    previous = None
    while time.monotonic() < deadline:
        pods = json.loads(kube("get", "pods", "-l", "cnpg.io/cluster=shop-postgres,cnpg.io/podRole=instance", "-o", "json"))["items"]
        state = [(p["metadata"]["name"], p["metadata"]["uid"], ready(p), bool(p["metadata"].get("deletionTimestamp"))) for p in pods]
        if state != previous:
            emit(f"t={time.monotonic() - deletion_start:.2f}s Pod(name, UID, ready, deleting): {state}")
            previous = state
        new_pods = [p for p in pods if p["metadata"]["uid"] != before["metadata"]["uid"]
                    and not p["metadata"].get("deletionTimestamp") and ready(p)]
        if new_pods and ready(get("cluster", "shop-postgres")):
            after = new_pods[0]
            recovery_seconds = round(time.monotonic() - deletion_start, 2)
            break
        time.sleep(0.5)
    else:
        raise AssertionError("Operator did not restore a ready PostgreSQL Pod within 180s")
    time.sleep(3)
finally:
    stop.set()
    for thread in threads:
        thread.join()
    with (args.output / "requests.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["utc", "elapsed", "path", "status", "error"])
        writer.writeheader()
        writer.writerows(sorted(samples, key=lambda r: r["elapsed"]))

pvc_after = get("pvc", claim)
assert pvc_after["metadata"]["uid"] == pvc_before["metadata"]["uid"]
assert pvc_after["spec"]["volumeName"] == pvc_before["spec"]["volumeName"]
assert any(v.get("persistentVolumeClaim", {}).get("claimName") == claim for v in after["spec"]["volumes"])
assert any(o["kind"] == "Cluster" and o["uid"] == cluster["metadata"]["uid"] for o in after["metadata"]["ownerReferences"])
code, body = request("/orders")
assert code == 200
orders_after = json.loads(body)
assert orders_after == orders_before, "Order data changed during Pod replacement"
code, body = request("/order", {"item": "after-postgres-recovery", "quantity": 1})
assert code == 201
new_id = json.loads(body)["id"]
for attempt in range(60):
    rows = json.loads(request("/orders")[1])
    new_order = next(o for o in rows if o["id"] == new_id)
    if new_order["processed_at"]:
        break
    time.sleep(1)
else:
    raise AssertionError("Worker did not process a new order after recovery")
final_cluster = get("cluster", "shop-postgres")
assert final_cluster["metadata"]["uid"] == cluster["metadata"]["uid"]
assert final_cluster["spec"] == cluster["spec"]
assert final_cluster["status"]["readyInstances"] == 1 and ready(final_cluster)
(args.output / "cluster-after.yaml").write_text(kube("get", "cluster", "shop-postgres", "-o", "yaml"))
emit(f"After: Pod={after['metadata']['name']}, UID={after['metadata']['uid']}")
emit(f"Recovery observed after {recovery_seconds}s; same PVC UID and PV, same Cluster UID/spec")
for path in ["/health", "/orders"]:
    counts = dict(Counter(str(r["status"]) for r in samples if r["path"] == path))
    emit(f"Observed HTTP {path}: {counts}")
    if path == "/health":
        assert counts and set(counts) == {"200"}, "API process became unhealthy during DB recovery"
emit(f"PASS: all {len(orders_before)} existing orders unchanged; new order {new_id} processed by {new_order['processed_by']}")
emit("SPEC (desired): " + json.dumps({k: final_cluster["spec"][k] for k in ["instances", "imageName", "storage", "bootstrap"]}))
emit("STATUS (observed): " + json.dumps({k: final_cluster["status"][k] for k in ["instances", "readyInstances", "currentPrimary", "phase"]}))
emit(kube("get", "pods,pvc,cluster").strip())
emit("PASS: operator reconciliation completed; retained storage and PostgreSQL data")
