"""Temporarily remove the kind apiserver static Pod; restore it in finally.

Only the apiserver manifest is moved. An independent in-node watchdog also
restores it after 180s if the experiment process is interrupted.
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
import uuid


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--context", default="kind-lab2")
parser.add_argument("--node", default="lab2-control-plane")
parser.add_argument("--url", default="http://172.20.0.2:30080")
parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts.local/04-control-plane")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
lab = Path(__file__).resolve().parents[1]
manifest = "/etc/kubernetes/manifests/kube-apiserver.yaml"
held = f"/etc/kubernetes/kube-apiserver.lab4-{uuid.uuid4().hex}.yaml"
log = []


def emit(message):
    print(message, flush=True)
    log.append(message)
    (args.output / "summary.txt").write_text("\n".join(log) + "\n")


def run(command, data=None, timeout=20, check=True):
    result = subprocess.run(command, input=data, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"{command}: {result.stdout}{result.stderr}")
    return result


def kube(*params, **kwargs):
    return run(["kubectl", "--context", args.context, "--request-timeout=3s", *params], **kwargs)


def node(*params, **kwargs):
    return run(["docker", "exec", args.node, *params], **kwargs)


def apiservers():
    return json.loads(node("crictl", "ps", "--name", "kube-apiserver", "-o", "json").stdout)["containers"]


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


def get_pods():
    return json.loads(kube("get", "pods", "-n", "shop", "-o", "json").stdout)["items"]


assert kube("get", "--raw", "/readyz").stdout == "ok"
assert apiservers(), "Expected a running static apiserver Pod"
assert node("test", "-f", manifest, check=False).returncode == 0
before = get_pods()
assert len(before) == 6
before_uids = {p["metadata"]["name"]: p["metadata"]["uid"] for p in before}
before_restarts = {p["metadata"]["name"]: [c["restartCount"] for c in p["status"]["containerStatuses"]] for p in before}
code, body = request("/orders")
assert code == 200
orders_before = json.loads(body)
history_before = json.loads(run(["helm", "--kube-context", args.context, "history", "shop", "-n", "shop", "-o", "json"]).stdout)
assert not kube("get", "configmap", "lab4-control-plane-probe", "-n", "shop", "--ignore-not-found", "-o", "name").stdout.strip()
emit("CONTROL PLANE FAILURE / apiserver static Pod")
emit(f"Before: {len(before)} ready workload Pods, {len(orders_before)} orders, shop revision {history_before[-1]['revision']}")
start = time.monotonic()
phase = "baseline"
samples = []
stop = threading.Event()


def probe(path):
    while not stop.is_set():
        row = {"utc": datetime.now(timezone.utc).isoformat(), "elapsed": round(time.monotonic() - start, 3),
               "phase": phase, "path": path, "status": 0, "error": ""}
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
    # Use positional parameters, not shell interpolation of paths.
    run(["docker", "exec", "-d", args.node, "sh", "-c",
         'sleep 180; if [ -f "$1" ]; then mv -- "$1" "$2"; fi', "lab4-restore", held, manifest])
    phase = "stopping"
    node("mv", "--", manifest, held)
    deadline = time.monotonic() + 60
    while apiservers():
        if time.monotonic() > deadline:
            raise AssertionError("Static apiserver did not stop within 60s")
        time.sleep(0.5)
    phase = "apiserver-down"
    down_start = time.monotonic()
    emit("Apiserver stopped: crictl reports no running kube-apiserver container")
    manifest_data = json.dumps({"apiVersion": "v1", "kind": "ConfigMap",
                                "metadata": {"name": "lab4-control-plane-probe", "namespace": "shop"},
                                "data": {"experiment": "must-not-be-created-while-apiserver-is-down"}})
    attempt = kube("apply", "--validate=false", "-f", "-", data=manifest_data, check=False)
    emit(f"kubectl apply while down: exit={attempt.returncode}\n{attempt.stdout}{attempt.stderr}".strip())
    assert attempt.returncode != 0
    (args.output / "kubectl-failure.txt").write_text(attempt.stdout + attempt.stderr)
    attempt = run(["helm", "upgrade", "shop", str(lab / "shop"), "--kube-context", args.context,
                   "-n", "shop", "-f", str(lab / "shop/values.yaml"), "--set", "api.replicas=4", "--timeout", "5s"], check=False)
    emit(f"helm upgrade while down: exit={attempt.returncode}\n{attempt.stdout}{attempt.stderr}".strip())
    assert attempt.returncode != 0
    (args.output / "helm-failure.txt").write_text(attempt.stdout + attempt.stderr)
    code, body = request("/order", {"item": "while-apiserver-down", "quantity": 1})
    assert code == 201
    new_id = json.loads(body)["id"]
    for attempt in range(30):
        code, body = request("/orders")
        assert code == 200
        new_order = next(o for o in json.loads(body) if o["id"] == new_id)
        if new_order["processed_at"]:
            break
        time.sleep(0.5)
    else:
        raise AssertionError("Worker did not process an order with apiserver stopped")
    emit(f"With apiserver down: order {new_id} created and processed by {new_order['processed_by']}")
    while time.monotonic() - down_start < 25:
        time.sleep(0.2)
    assert not apiservers(), "Apiserver resumed before the outage check ended"
    down_seconds = round(time.monotonic() - down_start, 2)
    emit(f"Verified apiserver-down interval: {down_seconds}s; application probes running via NodePort")
finally:
    phase = "restoring"
    try:
        if node("test", "-f", held, check=False).returncode == 0:
            node("mv", "--", held, manifest)
            emit("Restored static Pod manifest to kubelet directory")
        deadline = time.monotonic() + 120
        while True:
            result = kube("get", "--raw", "/readyz", check=False)
            if result.returncode == 0 and result.stdout == "ok":
                emit("Control plane recovered: /readyz = ok")
                break
            if time.monotonic() > deadline:
                raise AssertionError("Apiserver manifest restored, but /readyz did not recover")
            time.sleep(1)
        phase = "recovered"
        time.sleep(3)
    finally:
        stop.set()
        for thread in threads:
            thread.join()
        with (args.output / "requests.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=["utc", "elapsed", "phase", "path", "status", "error"])
            writer.writeheader()
            writer.writerows(sorted(samples, key=lambda r: r["elapsed"]))

assert not kube("get", "configmap", "lab4-control-plane-probe", "-n", "shop", "--ignore-not-found", "-o", "name").stdout.strip()
# Demonstrate real management writes after recovery, then remove the test object.
kube("apply", "-f", "-", data=manifest_data)
assert kube("get", "configmap", "lab4-control-plane-probe", "-n", "shop", "-o", "jsonpath={.data.experiment}").stdout == "must-not-be-created-while-apiserver-is-down"
kube("delete", "configmap", "lab4-control-plane-probe", "-n", "shop")
emit("After recovery: kubectl apply/get/delete ConfigMap succeeded; failed write had created nothing")
after = get_pods()
assert {p["metadata"]["name"]: p["metadata"]["uid"] for p in after} == before_uids
assert {p["metadata"]["name"]: [c["restartCount"] for c in p["status"]["containerStatuses"]] for p in after} == before_restarts
assert all(any(c["type"] == "Ready" and c["status"] == "True" for c in p["status"]["conditions"]) for p in after)
history_after = json.loads(run(["helm", "--kube-context", args.context, "history", "shop", "-n", "shop", "-o", "json"]).stdout)
assert history_after == history_before, "Failed Helm upgrade unexpectedly changed release history"
deployment = json.loads(kube("get", "deployment", "shop-api", "-n", "shop", "-o", "json").stdout)
assert deployment["spec"]["replicas"] == 3
code, body = request("/orders")
assert code == 200
orders_after = json.loads(body)
assert [o for o in orders_after if o["id"] != new_id] == orders_before
assert next(o for o in orders_after if o["id"] == new_id)["processed_at"]
for path in ["/health", "/orders"]:
    rows = [r for r in samples if r["path"] == path]
    down_rows = [r for r in rows if r["phase"] == "apiserver-down"]
    emit(f"HTTP {path}: all phases={dict(Counter(str(r['status']) for r in rows))}; apiserver-down={dict(Counter(str(r['status']) for r in down_rows))}")
    assert down_rows and all(r["status"] == 200 and not r["error"] for r in rows)
emit(f"PASS: all {len(orders_before)} existing orders retained; order {new_id} processed during outage")
emit("PASS: same 6 workload Pod UIDs and restart counts; API replicas=3; Helm history unchanged")
emit(kube("get", "pods,cluster", "-n", "shop").stdout.strip())
emit("PASS: control plane restored and cluster manageable")
