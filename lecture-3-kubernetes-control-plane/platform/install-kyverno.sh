#!/usr/bin/env bash
set -euo pipefail

platform_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cluster_name="${KIND_CLUSTER:-lab2}"
kube_context="${KUBE_CONTEXT:-kind-${cluster_name}}"
chart_version=3.9.2
app_version=v1.19.2

# The host can pull images, while DNS in the kind node may be unavailable.
# Preloading preserves the official image names and avoids editing upstream.
images=(
  "reg.kyverno.io/kyverno/kyvernopre:${app_version}"
  "reg.kyverno.io/kyverno/kyverno:${app_version}"
  "reg.kyverno.io/kyverno/reports-controller:${app_version}"
  "reg.kyverno.io/kyverno/kyverno-cli:${app_version}"
  "ghcr.io/kyverno/readiness-checker:${app_version}"
)
for image in "${images[@]}"; do
  docker pull "$image"
done
kind load docker-image --name "$cluster_name" "${images[@]}"

helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update kyverno
helm upgrade --install kyverno kyverno/kyverno \
  --version "$chart_version" --kube-context "$kube_context" \
  --namespace kyverno --create-namespace \
  -f "$platform_dir/kyverno-values.yaml" --wait --timeout 5m

kubectl --context "$kube_context" apply -f "$platform_dir/shop-namespace.yaml"
kubectl --context "$kube_context" apply -f "$platform_dir/../policies/guardrails.yaml"
kubectl --context "$kube_context" wait --for=condition=Ready \
  clusterpolicy/platform-guardrails --timeout=120s
