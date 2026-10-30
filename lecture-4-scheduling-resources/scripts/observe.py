"""Capture Kubernetes snapshots without credentials or Secret objects."""
import argparse
from pathlib import Path
import subprocess
from datetime import datetime, timezone

parser = argparse.ArgumentParser()
parser.add_argument("stage")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1] / "evidence"
root.mkdir(exist_ok=True)
with (root / (args.stage + ".txt")).open("w") as out:
    out.write(datetime.now(timezone.utc).isoformat() + "\n")
    for command in [
        ["get", "nodes", "-o", "wide"],
        ["-n", "shop", "get", "pods", "-o", "wide"],
        ["-n", "shop", "get", "pods", "-o", 'custom-columns=NAME:.metadata.name,QOS:.status.qosClass,PRIORITY:.spec.priority,REASON:.status.reason,MESSAGE:.status.message'],
        ["-n", "shop", "get", "events", "--sort-by=.metadata.creationTimestamp"],
        ["-n", "shop", "get", "pdb"],
    ]:
        cmd = ["kubectl", "--context", "kind-lab2", *command]
        out.write("\n$ " + " ".join(cmd) + "\n")
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out.write(result.stdout)
print(root / (args.stage + ".txt"))
