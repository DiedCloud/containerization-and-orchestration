for img in $(helm -n monitoring get manifest prometheus \
               | grep -oE 'image: "?[^" ]+' | awk '{print $2}' | tr -d '"' | sort -u); do
  echo "== $img"
  docker pull "$img"
  kind load docker-image "$img" --name lab2
done
kubectl -n monitoring delete pod --all
