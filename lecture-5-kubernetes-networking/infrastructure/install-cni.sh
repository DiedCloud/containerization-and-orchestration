#!/usr/bin/env bash
# Migrate the existing lab2 cluster, retaining its PVCs and monitoring releases.
set -euo pipefail
cd "$(dirname "$0")"
kubectl config use-context kind-lab2
helm repo add cilium https://helm.cilium.io/
helm upgrade --install cilium cilium/cilium --version 1.18.3 \
  -n kube-system -f cilium-values.yaml
kubectl -n kube-system rollout status daemonset/cilium --timeout=5m
kubectl -n kube-system delete daemonset kindnet --ignore-not-found
# Cilium installs 05-cilium.conflist and makes the old configuration inactive.
# Existing non-hostNetwork pods must acquire Cilium endpoints as well.
kubectl get pods -A -o json | python3 -c '
import json, subprocess, sys
for p in json.load(sys.stdin)["items"]:
    if not p["spec"].get("hostNetwork") and p["status"].get("phase") not in ("Succeeded", "Failed") and not p["metadata"]["name"].startswith("cilium"):
        subprocess.run(["kubectl", "-n", p["metadata"]["namespace"], "delete", "pod", p["metadata"]["name"], "--wait=false"], check=True)
'
