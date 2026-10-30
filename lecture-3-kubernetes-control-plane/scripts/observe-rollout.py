"""Probe the actual Service while a Helm command runs; save local evidence.

Example: python3 observe-rollout.py --url http://NODE_IP:30080 \
  --output artifacts.local/rolling -- helm upgrade ... --wait
"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.request


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", required=True)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--context", default="kind-lab2")
parser.add_argument("--expect-failure", action="store_true")
parser.add_argument("--min-ready", type=int, default=3)
parser.add_argument("--max-active", type=int, default=4)
parser.add_argument("command", nargs=argparse.REMAINDER)
args = parser.parse_args()
command = args.command[1:] if args.command[:1] == ["--"] else args.command
if not command:
    parser.error("Specify a command after --")
args.output.parent.mkdir(parents=True, exist_ok=True)
stop = threading.Event()
requests = []
snapshots = []
observation_errors = []
start = time.monotonic()


def probe():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with args.output.with_suffix(".csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["utc", "elapsed", "status", "version", "error"])
        writer.writeheader()
        while not stop.is_set():
            row = {"utc": datetime.now(timezone.utc).isoformat(),
                   "elapsed": round(time.monotonic() - start, 3),
                   "status": 0, "version": "", "error": ""}
            try:
                with opener.open(args.url.rstrip("/") + "/health", timeout=2) as response:
                    row["status"] = response.status
                    row["version"] = response.headers.get("X-Shop-Version", "")
                    if response.read() != b"ok":
                        row["error"] = "Unexpected body"
            except Exception as exc:
                row["error"] = str(exc)
            requests.append(row)
            writer.writerow(row)
            file.flush()
            stop.wait(0.1)


def sample():
    previous = None
    while not stop.is_set():
        try:
            result = subprocess.run(
                ["kubectl", "--context", args.context, "--request-timeout=5s", "get", "pods",
                 "-n", "shop", "-l", "app.kubernetes.io/name=api,app.kubernetes.io/instance=shop", "-o", "json"],
                capture_output=True, text=True, check=True, timeout=8,
            )
            groups = defaultdict(lambda: {"active": 0, "ready": 0, "image": "", "healthFail": ""})
            terminating = 0
            for pod in json.loads(result.stdout)["items"]:
                if pod["metadata"].get("deletionTimestamp"):
                    terminating += 1
                    continue
                group = groups[pod["metadata"]["labels"]["pod-template-hash"]]
                group["active"] += 1
                group["ready"] += any(c["type"] == "Ready" and c["status"] == "True"
                                      for c in pod.get("status", {}).get("conditions", []))
                container = pod["spec"]["containers"][0]
                group["image"] = container["image"]
                group["healthFail"] = next(e["value"] for e in container["env"] if e["name"] == "HEALTH_FAIL")
            snapshot = {"elapsed": round(time.monotonic() - start, 2), "groups": dict(groups),
                        "ready": sum(g["ready"] for g in groups.values()),
                        "active": sum(g["active"] for g in groups.values()), "terminating": terminating}
            snapshots.append(snapshot)
            signature = json.dumps([snapshot["groups"], terminating], sort_keys=True)
            if signature != previous:
                print(json.dumps(snapshot), flush=True)
                previous = signature
        except Exception as exc:
            observation_errors.append(str(exc))
            print(f"Observation error: {exc}", flush=True)
        stop.wait(0.5)


threads = [threading.Thread(target=probe), threading.Thread(target=sample)]
for thread in threads:
    thread.start()
try:
    time.sleep(3)
    print("COMMAND:", " ".join(command), flush=True)
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    print(result.stdout, end="", flush=True)
    print(result.stderr, end="", flush=True)
    args.output.with_suffix(".command.txt").write_text(result.stdout + result.stderr)
    time.sleep(5)
finally:
    stop.set()
    for thread in threads:
        thread.join()

errors = [r for r in requests if r["status"] != 200 or r["error"]]
summary = {
    "command": command, "returncode": result.returncode,
    "requests": len(requests), "errors": len(errors),
    "versions": dict(Counter(r["version"] for r in requests)),
    "min_ready": min((s["ready"] for s in snapshots), default=0),
    "max_active": max((s["active"] for s in snapshots), default=0),
    "observation_errors": observation_errors, "snapshots": snapshots,
}
args.output.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
print("SUMMARY:", json.dumps({k: v for k, v in summary.items() if k != "snapshots"}), flush=True)
assert requests and not errors, f"Health requests failed: {errors[:5]}"
assert not observation_errors, "Pod observation failed"
assert summary["min_ready"] >= args.min_ready, "Too few ready Pods during observation"
assert summary["max_active"] <= args.max_active, "Too many active Pods during observation"
assert (result.returncode != 0) == args.expect_failure, "Unexpected command exit status"
print("PASS: Service kept answering; rollout bounds held", flush=True)
