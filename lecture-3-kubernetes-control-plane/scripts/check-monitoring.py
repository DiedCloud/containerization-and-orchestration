"""Verify existing monitoring, trigger ShopWorkerStalled and restore workers.

Uses temporary localhost port-forwards. Detailed evidence stays out of Git.
"""
import argparse
import base64
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--context", default="kind-lab2")
parser.add_argument("--url", default="http://172.20.0.2:30080")
parser.add_argument("--hold-seconds", type=int, default=0)
parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "artifacts.local/05-monitoring")
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
log = []
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def emit(message):
    print(message, flush=True)
    log.append(message)
    (args.output / "summary.txt").write_text("\n".join(log) + "\n")


def kube(*params):
    return subprocess.check_output(["kubectl", "--context", args.context, "--request-timeout=15s", *params], text=True, timeout=70)


def http(url, data=None, authorization=None):
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    request = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with opener.open(request, timeout=10) as response:
        body = response.read().decode()
        return json.loads(body) if body[:1] in {"{", "["} else body


def query(expression):
    data = http("http://127.0.0.1:9090/api/v1/query?" + urllib.parse.urlencode({"query": expression}))
    assert data["status"] == "success", data
    return data["data"]["result"]


def forward(stack, service, port, health):
    try:
        http(f"http://127.0.0.1:{port}{health}")
        return
    except Exception:
        pass
    file = stack.enter_context((args.output / f"forward-{service}.log").open("w"))
    process = subprocess.Popen(["kubectl", "--context", args.context, "-n", "monitoring", "port-forward",
                                "svc/" + service, f"{port}:80" if service != "alertmanager" else f"{port}:9093"],
                               stdout=file, stderr=subprocess.STDOUT)
    def cleanup():
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    stack.callback(cleanup)
    for attempt in range(100):
        if process.poll() is not None:
            raise RuntimeError(f"Port-forward {service} exited; inspect its local log")
        try:
            http(f"http://127.0.0.1:{port}{health}")
            return
        except Exception:
            time.sleep(0.2)
    raise AssertionError(f"Service {service} not accessible")


with ExitStack() as stack:
    forward(stack, "prometheus-server", 9090, "/-/ready")
    forward(stack, "grafana", 3000, "/api/health")
    # Alertmanager chart exposes its web UI on Service port 9093.
    forward(stack, "alertmanager", 9093, "/-/ready")
    secret = json.loads(kube("get", "secret", "grafana", "-n", "monitoring", "-o", "json"))["data"]
    credentials = base64.b64decode(secret["admin-user"]) + b":" + base64.b64decode(secret["admin-password"])
    authorization = "Basic " + base64.b64encode(credentials).decode()
    dashboard = http("http://127.0.0.1:3000/api/dashboards/uid/shop-platform", authorization=authorization)
    assert dashboard["meta"]["provisioned"] and len(dashboard["dashboard"]["panels"]) == 8
    assert http("http://127.0.0.1:3000/api/dashboards/uid/ad6fljv", authorization=authorization)["dashboard"]["title"] == "RED"
    (args.output / "dashboard-api.json").write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
    for attempt in range(60):
        targets = http("http://127.0.0.1:9090/api/v1/targets?state=active")["data"]["activeTargets"]
        shop_targets = [t for t in targets if t["labels"].get("job", "").startswith("serviceMonitor/shop/")]
        groups = http("http://127.0.0.1:9090/api/v1/rules")["data"]["groups"]
        shop_rules = [r for g in groups if g["name"].startswith("shop-cr/") for r in g["rules"]]
        if len(shop_targets) == 5 and all(t["health"] == "up" and not t["lastError"] for t in shop_targets) and len(shop_rules) == 3 and all(r["health"] == "ok" and r["state"] == "inactive" for r in shop_rules):
            break
        time.sleep(2)
    else:
        raise AssertionError("Monitoring not healthy before the experiment")
    assert len([t for t in targets if t["labels"].get("job") == "api" and t["health"] == "up"]) == 3
    assert any(g["name"] == "api-health" and len(g["rules"]) == 3 for g in groups)
    emit("SHOP MONITORING / existing Lab 2 stack")
    emit("Baseline: 3 API + 2 worker scrape targets UP; 3 shop rules healthy/inactive")
    emit("Lab 2 preserved: 3 API targets UP, 3 api-health rules, RED dashboard")
    emit("Grafana: provisioned dashboard shop-platform, 8 panels, existing Prometheus datasource")
    (args.output / "targets-before.json").write_text(json.dumps([
        {"labels": t["labels"], "health": t["health"], "lastError": t["lastError"]} for t in shop_targets], indent=2))
    stop = threading.Event()
    traffic_errors = []
    traffic_requests = []
    def traffic():
        while not stop.is_set():
            try:
                assert http(args.url + "/health") == "ok"
                assert isinstance(http(args.url + "/orders"), list)
                traffic_requests.append(time.time())
            except Exception as exc:
                traffic_errors.append(str(exc))
            stop.wait(0.5)
    thread = threading.Thread(target=traffic)
    thread.start()
    pending_id = None
    try:
        emit(kube("scale", "deployment/shop-worker", "-n", "shop", "--replicas=0").strip())
        kube("wait", "--for=delete", "pod", "-n", "shop", "-l", "app=shop-worker", "--timeout=60s")
        pending = http(args.url + "/order", {"item": "monitoring-worker-outage", "quantity": 1})
        pending_id = pending["id"]
        assert not pending["processed_at"]
        emit(f"Worker replicas=0; order {pending_id} persisted and awaits processing; API remains available")
        started = time.monotonic()
        previous = None
        while time.monotonic() - started < 180:
            alerts = http("http://127.0.0.1:9090/api/v1/alerts")["data"]["alerts"]
            alert = next((a for a in alerts if a["labels"].get("alertname") == "ShopWorkerStalled"), None)
            state = alert["state"] if alert else "inactive"
            if state != previous:
                emit(f"ShopWorkerStalled: {state}")
                previous = state
            if state == "firing":
                break
            time.sleep(3)
        else:
            raise AssertionError("Worker alert did not reach firing")
        emit(f"FIRING after {time.monotonic() - started:.1f}s: ShopWorkerStalled, severity=warning, service=shop-worker")
        (args.output / "prometheus-firing.json").write_text(json.dumps(alert, indent=2, ensure_ascii=False))
        deadline = time.monotonic() + 90
        while True:
            am_alerts = http("http://127.0.0.1:9093/api/v2/alerts")
            am_alert = next((a for a in am_alerts if a["labels"].get("alertname") == "ShopWorkerStalled"), None)
            if am_alert:
                break
            assert time.monotonic() < deadline, "Alertmanager did not receive the alert"
            time.sleep(3)
        (args.output / "alertmanager-firing.json").write_text(json.dumps(am_alert, indent=2, ensure_ascii=False))
        emit("Existing Alertmanager received ShopWorkerStalled: " + am_alert["status"]["state"])
        for panel in dashboard["dashboard"]["panels"]:
            result = query(panel["targets"][0]["expr"])
            if panel["id"] == 8:
                assert not result, "Worker heartbeat should be absent while all workers are stopped"
            else:
                assert result, f"Dashboard panel has no data: {panel['title']}"
            (args.output / f"panel-{panel['id']}.json").write_text(json.dumps(result, indent=2))
        emit("Dashboard during fault: 7 queries return data; missing worker heartbeat is expected")
        if args.hold_seconds:
            emit(f"Holding firing state {args.hold_seconds}s for UI inspection: localhost:9090/alerts and localhost:3000/d/shop-platform")
            time.sleep(args.hold_seconds)
    finally:
        try:
            emit(kube("scale", "deployment/shop-worker", "-n", "shop", "--replicas=2").strip())
            kube("rollout", "status", "deployment/shop-worker", "-n", "shop", "--timeout=120s")
            emit("Restored worker replicas=2")
        finally:
            stop.set()
            thread.join()
    for attempt in range(60):
        orders = http(args.url + "/orders")
        processed = next(o for o in orders if o["id"] == pending_id)
        if processed["processed_at"]:
            break
        time.sleep(1)
    else:
        raise AssertionError("Pending order was not processed after worker recovery")
    for attempt in range(60):
        targets = http("http://127.0.0.1:9090/api/v1/targets?state=active")["data"]["activeTargets"]
        shop_targets = [t for t in targets if t["labels"].get("job", "").startswith("serviceMonitor/shop/")]
        alerts = http("http://127.0.0.1:9090/api/v1/alerts")["data"]["alerts"]
        if len(shop_targets) == 5 and all(t["health"] == "up" for t in shop_targets) and not any(a["labels"].get("alertname", "").startswith("Shop") for a in alerts):
            break
        time.sleep(2)
    else:
        raise AssertionError("Targets or alert state failed to recover")
    assert not traffic_errors, traffic_errors
    for panel in dashboard["dashboard"]["panels"]:
        assert query(panel["targets"][0]["expr"]), f"Recovered dashboard has no data: {panel['title']}"
    emit("All 8 dashboard queries return data after recovery")
    emit(f"PASS: worker 2/2, all 5 targets UP, shop alerts inactive; queued order {pending_id} processed")
    emit(f"API during fault/recovery: {len(traffic_requests)} successful health+orders pairs, errors={len(traffic_errors)}")
    emit(f"Orders after experiment: {len(orders)}; shop release configuration still declares 2 workers")
    emit("PASS: existing Prometheus, Grafana and Alertmanager verified; no second stack installed")
