#!/usr/bin/env bash
# All shop changes must also synchronize the existing monitoring releases.
set -euo pipefail
platform_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
lab_dir="$(dirname "$platform_dir")"
cluster_name="${KIND_CLUSTER:-lab2}"
kube_context="${KUBE_CONTEXT:-kind-${cluster_name}}"
action="${1:-}"
if [[ "$action" != upgrade && "$action" != rollback ]]; then
  echo "Usage: bash $0 upgrade [Helm flags] | rollback REVISION [Helm flags]" >&2
  exit 2
fi
shift
if [[ "$action" == rollback ]]; then
  revision="${1:?Specify rollback revision}"
  shift
  command=(helm rollback shop "$revision" --kube-context "$kube_context" -n shop --wait --timeout 5m "$@")
else
  command=(helm upgrade --install shop "$lab_dir/shop" --kube-context "$kube_context" -n shop
    --create-namespace -f "$lab_dir/shop/values.yaml" --wait --timeout 5m "$@")
fi
helm_status=0
"${command[@]}" || helm_status=$?
# A failed rollout may still have applied CR changes. Synchronize those too,
# retaining Helm's failure status so the caller cannot mistake it for success.
python3 "$lab_dir/scripts/sync-monitoring.py" --context "$kube_context"
exit "$helm_status"
