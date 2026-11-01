#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
helm repo add linkerd-edge https://helm.linkerd.io/edge
helm repo update linkerd-edge
# Keys stay outside git and are retained for subsequent upgrades.
cert_dir="${LINKERD_CERT_DIR:-$HOME/.local/share/lab6-linkerd}"
mkdir -p "$cert_dir"
chmod 700 "$cert_dir"
if [ ! -f "$cert_dir/issuer.key" ]; then
  umask 077
  openssl ecparam -name prime256v1 -genkey -noout -out "$cert_dir/root.key"
  openssl req -new -x509 -key "$cert_dir/root.key" -out "$cert_dir/root.crt" -days 365 -subj /CN=root.linkerd.cluster.local -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign,cRLSign
  openssl ecparam -name prime256v1 -genkey -noout -out "$cert_dir/issuer.key"
  openssl req -new -key "$cert_dir/issuer.key" -out "$cert_dir/issuer.csr" -subj /CN=identity.linkerd.cluster.local
  printf 'basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n' > "$cert_dir/issuer.ext"
  openssl x509 -req -in "$cert_dir/issuer.csr" -CA "$cert_dir/root.crt" -CAkey "$cert_dir/root.key" -CAcreateserial -out "$cert_dir/issuer.crt" -days 90 -extfile "$cert_dir/issuer.ext"
fi
python3 platform-policy.py
helm upgrade --install linkerd-crds linkerd-edge/linkerd-crds --version 2026.10.2 -n linkerd --create-namespace
helm upgrade --install linkerd-control-plane linkerd-edge/linkerd-control-plane --version 2026.10.2 -n linkerd \
  -f linkerd-values.yaml --set-file identityTrustAnchorsPEM="$cert_dir/root.crt" \
  --set-file identity.issuer.tls.crtPEM="$cert_dir/issuer.crt" --set-file identity.issuer.tls.keyPEM="$cert_dir/issuer.key" \
  --wait --timeout 5m
