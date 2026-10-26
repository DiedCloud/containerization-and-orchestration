for img in \
  quay.io/prometheus/alertmanager:v0.34.1 \
  quay.io/prometheus-operator/prometheus-config-reloader:v0.94.2
do
  docker pull "$img" &&
  kind load docker-image "$img" --name lab2
done
