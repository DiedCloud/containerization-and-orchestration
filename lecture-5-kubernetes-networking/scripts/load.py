"""One fresh HTTP connection per order; no retries, including on network errors."""
import argparse
import concurrent.futures
import json
import time
import threading
import urllib.request

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--url', default='http://shop-api.shop.svc.cluster.local:8000')
p.add_argument('--duration', type=int, default=180)
p.add_argument('--rate', type=float, default=10)
a = p.parse_args()
output_lock = threading.Lock()

def request(index):
    start = time.time()
    try:
        req = urllib.request.Request(a.url + '/order', data=json.dumps({'item': f'chaos-{index}', 'quantity': 1}).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
            ok, code = r.status == 201 and isinstance(data.get('id'), int), r.status
    except Exception as exc:
        ok, code = False, str(exc)
    with output_lock:
        print(json.dumps({'time': start, 'duration_ms': (time.time()-start)*1000, 'ok': ok, 'code': code}), flush=True)

start = time.monotonic()
with concurrent.futures.ThreadPoolExecutor(max_workers=30) as pool:
    for i in range(int(a.duration*a.rate)):
        time.sleep(max(0, start+i/a.rate-time.monotonic()))
        pool.submit(request, i)
