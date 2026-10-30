#!/usr/bin/env bash
set -euo pipefail
platform_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cluster_name="${KIND_CLUSTER:-lab2}"
kube_context="${KUBE_CONTEXT:-kind-${cluster_name}}"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm upgrade --install shop-monitoring-crds prometheus-community/prometheus-operator-crds \
  --version 32.0.2 --kube-context "$kube_context" -n monitoring \
  -f "$platform_dir/monitoring-crds-values.yaml" --wait --timeout 2m
kubectl --context "$kube_context" wait --for=condition=Established \
  crd/servicemonitors.monitoring.coreos.com crd/prometheusrules.monitoring.coreos.com --timeout=60s
