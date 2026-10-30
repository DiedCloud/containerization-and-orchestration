"""Temporary, context-specific access to monitoring; no reused local forwards."""
from contextlib import contextmanager
import json
import re
import subprocess
import tempfile
import time
import urllib.request


@contextmanager
def service_api(context, service, service_port=80):
    with tempfile.TemporaryFile(mode="w+") as log:
        process = subprocess.Popen(
            ["kubectl", "--context", context, "-n", "monitoring", "port-forward",
             "--address=127.0.0.1", "svc/" + service, f":{service_port}"],
            stdout=log, stderr=subprocess.STDOUT,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            deadline = time.monotonic() + 30
            while True:
                log.seek(0)
                output = log.read()
                match = re.search(r"Forwarding from 127\.0\.0\.1:(\d+) ->", output)
                if match:
                    break
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f"Port-forward {service} failed: {output}")
                time.sleep(0.1)
            base = "http://127.0.0.1:" + match[1]

            def get(path, authorization=None):
                headers = {"Authorization": authorization} if authorization else {}
                with opener.open(urllib.request.Request(base + path, headers=headers), timeout=10) as response:
                    body = response.read().decode()
                    return json.loads(body) if body[:1] in {"{", "["} else body

            yield get
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
