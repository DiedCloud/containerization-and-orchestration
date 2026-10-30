#!/usr/bin/env bash
set -euo pipefail
platform_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cluster_name="${KIND_CLUSTER:-lab2}"
kube_context="${KUBE_CONTEXT:-kind-${cluster_name}}"
operator_image=ghcr.io/cloudnative-pg/cloudnative-pg:1.30.1
postgres_image=ghcr.io/cloudnative-pg/postgresql:17.7

docker pull "$operator_image"
docker pull "$postgres_image"
kind load docker-image --name "$cluster_name" "$operator_image" "$postgres_image"
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm upgrade --install cnpg cnpg/cloudnative-pg --version 0.29.1 \
  --kube-context "$kube_context" -n cnpg-system --create-namespace \
  -f "$platform_dir/cnpg-values.yaml" --wait --timeout 5m
kubectl --context "$kube_context" wait --for=condition=Established \
  crd/clusters.postgresql.cnpg.io --timeout=60s
