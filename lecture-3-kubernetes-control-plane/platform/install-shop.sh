#!/usr/bin/env bash
set -euo pipefail
platform_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
lab_dir="$(dirname "$platform_dir")"
cluster_name="${KIND_CLUSTER:-lab2}"
kube_context="${KUBE_CONTEXT:-kind-${cluster_name}}"

# Prerequisites: install-kyverno.sh, then install-cnpg.sh.
kubectl --context "$kube_context" wait --for=condition=Ready \
  clusterpolicy/platform-guardrails --timeout=60s
kubectl --context "$kube_context" get crd clusters.postgresql.cnpg.io >/dev/null
bash "$platform_dir/install-monitoring-crds.sh"
for version in 1.0.0 1.1.0; do
  docker build --build-arg "APP_VERSION=$version" \
    -t "docker.io/library/shop:$version" "$lab_dir/services"
done
kind load docker-image --name "$cluster_name" \
  docker.io/library/shop:1.0.0 docker.io/library/shop:1.1.0
helm lint "$lab_dir/shop"
helm template shop "$lab_dir/shop" -n shop |
  kubectl --context "$kube_context" apply --dry-run=server -f -
helm upgrade --install shop "$lab_dir/shop" --kube-context "$kube_context" \
  -n shop --create-namespace -f "$lab_dir/shop/values.yaml" --wait --timeout 5m
kubectl --context "$kube_context" wait --for=condition=Ready \
  cluster/shop-postgres -n shop --timeout=180s
kubectl --context "$kube_context" get pods,svc -n shop
python3 "$lab_dir/scripts/sync-monitoring.py" --context "$kube_context"
