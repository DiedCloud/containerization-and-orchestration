"""Set scheduler capacity and enable real kubelet memory eviction on worker.

Reservations constrain scheduling in kind (the physical host has 16 CPUs).
Memory threshold is set separately for the experiment, never disable OOM limits.
"""
import argparse
import json
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--node", default="lab2-worker")
parser.add_argument("--reserved-cpu", default="14")
parser.add_argument("--memory-threshold", default="100Mi")
args = parser.parse_args()
# Preserve the remaining kubelet settings; no YAML package needed on the host.
config = subprocess.check_output(["docker", "exec", args.node, "cat", "/var/lib/kubelet/config.yaml"], text=True)
import re
for key, value in {"kubeReserved": {"cpu": args.reserved_cpu},
                   "evictionHard": {"memory.available": args.memory_threshold,
                                    "nodefs.available": "0%", "imagefs.available": "0%", "nodefs.inodesFree": "0%"}}.items():
    config = re.sub(r"^" + key + r":[^\n]*\n(?:[ \t]+[^\n]*\n)*", "", config, flags=re.M)
    config += key + ": " + json.dumps(value) + "\n"
subprocess.run(["docker", "exec", "-i", args.node, "cp", "/dev/stdin", "/var/lib/kubelet/config.yaml"], input=config, text=True, check=True)
subprocess.run(["docker", "exec", args.node, "systemctl", "restart", "kubelet"], check=True)
print(args.node, "reserved CPU", args.reserved_cpu, "memory eviction threshold", args.memory_threshold)
