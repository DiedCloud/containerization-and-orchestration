kubectl -n monitoring get daemonset alloy \
  -o jsonpath='{range .spec.template.spec.containers[*]}{.image}{"\n"}{end}' \
  | while read -r img; do
      docker pull "$img" &&
      kind load docker-image "$img" --name lab2
    done

kubectl -n monitoring rollout restart daemonset/alloy
kubectl -n monitoring rollout status daemonset/alloy --timeout=120s
