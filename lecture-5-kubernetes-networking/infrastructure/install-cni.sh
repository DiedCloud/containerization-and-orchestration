#!/usr/bin/env bash
# Migrate the existing lab2 cluster, retaining its PVCs and monitoring releases.
set -euo pipefail
cd "$(dirname "$0")"
kubectl config use-context kind-lab2
helm repo add cilium https://helm.cilium.io/
python3 preload-images.py
helm upgrade --install cilium cilium/cilium --version 1.20.4 \
  -n kube-system -f cilium-values.yaml
kubectl -n kube-system rollout status daemonset/cilium --timeout=5m
kubectl -n kube-system delete daemonset kindnet --ignore-not-found
# Cilium installs 05-cilium.conflist and makes the old configuration inactive.
# Restart only old, unmanaged pods; already migrated endpoints are retained.
kubectl get pods -A -o json | python3 -c '
import json, subprocess, sys
pods = json.load(sys.stdin)["items"]
endpoints = json.loads(subprocess.check_output(["kubectl", "get", "ciliumendpoints", "-A", "-o", "json"]))["items"]
managed = {(p["metadata"]["namespace"], p["metadata"]["name"]) for p in endpoints}
for namespace in ["kube-system", "kyverno", "cnpg-system", "local-path-storage", "default", "monitoring", "shop"]:
    for p in pods:
        m = p["metadata"]
        if m["namespace"] != namespace or (namespace, m["name"]) in managed:
            continue
        if not p["spec"].get("hostNetwork") and p["status"].get("phase") not in ("Succeeded", "Failed") and not m["name"].startswith("cilium"):
            subprocess.run(["kubectl", "-n", namespace, "delete", "pod", m["name"], "--wait=false"], check=True)
    if namespace in ("kyverno", "cnpg-system"):
        subprocess.run(["kubectl", "-n", namespace, "rollout", "status", "deployment", "--timeout=3m"], check=True)
'
