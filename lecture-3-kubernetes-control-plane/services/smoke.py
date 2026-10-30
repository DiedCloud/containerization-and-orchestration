"""Run inside the compose api container: python /tmp/smoke.py."""
import concurrent.futures
import json
import time
import urllib.error
import urllib.request


def request(path, data=None, host="api"):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(f"http://{host}:8000{path}", body,
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


for attempt in range(60):
    try:
        if request("/health")[0] == 200:
            break
    except OSError:
        pass
    time.sleep(1)
else:
    raise AssertionError("api did not start")

assert request("/health") == (200, "ok")
assert request("/health", host="broken-api")[0] == 503
assert request("/order", {"item": "", "quantity": 0})[0] == 422
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
    results = list(pool.map(lambda i: request("/order", {"item": f"smoke-{i}", "quantity": 2}), range(50)))
assert all(status == 201 for status, _ in results), results
ids = {json.loads(body)["id"] for _, body in results}
assert len(ids) == 50
for attempt in range(60):
    status, body = request("/orders")
    orders = [o for o in json.loads(body) if o["id"] in ids]
    if len(orders) == 50 and all(o["processed_at"] is not None for o in orders):
        break
    time.sleep(1)
else:
    raise AssertionError("workers failed to process orders")
assert all(o["processed_by"] for o in orders)
assert "shop_http_requests_total" in request("/metrics")[1]
print("PASS: /health=200; HEALTH_FAIL=503; invalid order=422")
print("PASS: 50 concurrent orders persisted and processed; /metrics available")
print("Workers observed:", sorted({o["processed_by"] for o in orders}))
