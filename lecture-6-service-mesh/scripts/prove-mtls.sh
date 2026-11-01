#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
ip=$(kubectl -n shop6 get pod -l app=shop-api,version=v1 -o jsonpath='{.items[0].status.podIP}')
root="${LINKERD_CERT_DIR:-$HOME/.local/share/lab6-linkerd}/root.crt"
docker exec -i lab2-worker tee /tmp/lab6-root.crt < "$root" >/dev/null
printf 'Server IP: %s; expected identity: shop-api-v1.shop6.serviceaccount.identity.linkerd.cluster.local\n' "$ip"
# A TLS 1.3 peer authenticates itself before refusing our missing client certificate.
timeout 8 docker exec lab2-worker openssl s_client -connect "$ip:8000" \
  -servername shop-api-v1.shop6.serviceaccount.identity.linkerd.cluster.local \
  -verify_hostname shop-api-v1.shop6.serviceaccount.identity.linkerd.cluster.local \
  -verify_return_error -CAfile /tmp/lab6-root.crt -showcerts </dev/null 2>&1 || true
printf '\nAuthenticated request through meshed client:\n'
kubectl -n shop6 exec deploy/shop-client -c client -- python -c 'import urllib.request; print(urllib.request.urlopen("http://shop-api:8000/version").read().decode())'
printf '\nPlaintext request without mesh (must be denied):\n'
docker exec lab2-worker curl -s -o /dev/null -w 'HTTP %{http_code}\n' "http://$ip:8000/version"
printf '\nRequest between two different API pods:\n'
source_pod=$(kubectl -n shop6 get pods -l app=shop-api,version=v1 -o jsonpath='{.items[1].metadata.name}')
kubectl -n shop6 exec "$source_pod" -c api -- python -c "import urllib.request; print(urllib.request.urlopen('http://$ip:8000/version').read().decode())"
printf '\nMesh inbound TLS counters (certificate identity, not IP):\n'
kubectl -n shop6 exec deploy/shop-client -c client -- python -c "import urllib.request; print('\n'.join(x for x in urllib.request.urlopen('http://$ip:4191/metrics').read().decode().splitlines() if x.startswith('tcp_open_total') and 'tls=' in x))"
