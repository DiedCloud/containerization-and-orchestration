# Запуск опытов

Результаты — в [REPORT.md](REPORT.md). Команды выполнять из каталога лабораторной. Нужны Docker, kind, kubectl, Helm, Python 3; для графика — matplotlib, для диагностики — Hubble CLI. Используется существующий `kind-lab2` с двумя нодами, CNPG, Kyverno и мониторингом Лабы 2. Chart приложения продолжает Лабы 3–4; исходники и образы `shop:1.1.0` / `shop:1.1.1` — из Лабы 3.

```bash
docker start lab2-control-plane lab2-worker
kubectl config use-context kind-lab2
bash infrastructure/install-cni.sh
helm lint shop
# Сверить адреса инфраструктуры с nodeCIDRs/apiServerCIDRs в shop/values.yaml:
kubectl get ciliumnodes -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.addresses}{"\n"}{end}'
# Если адреса отличаются, перенести InternalIP control-plane/worker как точные /32.
# Весь PodCIDR разрешать нельзя: это откроет доступ посторонним Pod.
# В финальном values политики включены; только для исследования плоской сети:
bash scripts/upgrade.sh --set networkPolicy.enabled=false --wait=legacy --timeout 4m
kubectl -n shop wait --for=condition=Ready cluster/shop-postgres --timeout=180s
python3 scripts/inspect-network.py
bash scripts/run-chaos.sh
```

`run-chaos.sh` запускает два клиента по 10 POST /order в секунду на три минуты и удаляет случайный Ready API/worker каждые 7 секунд. Внешний клиент идёт через DNS Docker `lab2-control-plane:30080`, внутренний — через DNS Kubernetes `shop-api.shop.svc.cluster.local:8000`. Повторных HTTP-попыток нет. Скрипт сохраняет полный stdout и график в игнорируемый `results/`. Во время опыта не перезапускать kubelet: это оборвёт канал `kubectl exec`, через который собирается stdout внутреннего клиента. Пауза хоста более 3 секунд делает измерение непригодным; построение графика её обнаруживает.

```bash
# Вернуть финальные defaults, включая zero-trust:
bash scripts/upgrade.sh --wait=legacy --timeout 4m
python3 scripts/matrix.py --output results/matrix.json

# Выбор поломки скрыт до диагностики:
python3 scripts/break.py
kubectl -n shop exec deployment/shop-client -- python -c \
  'import urllib.request; r=urllib.request.Request("http://shop-api:8000/order",data=b"{\"item\":\"diagnostic\",\"quantity\":1}",headers={"Content-Type":"application/json"});print(urllib.request.urlopen(r,timeout=10).read())'
```

В отдельном терминале открыть Hubble:

```bash
kubectl -n kube-system port-forward svc/hubble-relay 4245:80
# В другом терминале:
hubble observe --server localhost:4245 --namespace shop --verdict DROPPED --follow
```

Сопоставить source/destination, порт и `Policy denied` с живыми метками Pod и NetworkPolicy. После определения причины посмотреть конкретный override в `results/fault-values.yaml` и исправить values; `upgrade.sh` без overrides возвращает рабочие defaults.

```bash
bash scripts/upgrade.sh --wait=legacy --timeout 4m
python3 scripts/matrix.py --output results/matrix-restored.json
python3 scripts/sync-monitoring.py --context kind-lab2 --output results/monitoring
```

Адаптер загружает ServiceMonitor/PrometheusRule в существующий обычный Prometheus Лабы 2, сохраняет его jobs/правила и настройки Alertmanager, проверяет правила через promtool и API. Это не Prometheus Operator; после изменения CR синхронизацию нужно повторить.

```bash
kubectl -n monitoring port-forward svc/prometheus-server 9090:80
kubectl -n monitoring port-forward svc/grafana 3001:80
kubectl -n kube-system port-forward svc/hubble-ui 12000:80
```

Команды port-forward запускать в отдельных терминалах. Интерфейсы: `http://127.0.0.1:9090/alerts`, `http://127.0.0.1:3001/d/shop-network`, `http://127.0.0.1:12000/?namespace=shop`. Логин Grafana от Лабы 2.

Для проверки алерта (при рабочем shop):

```bash
python3 scripts/provoke-alert.py --duration 150
```

Stranger пытается подключиться к PostgreSQL и получает deny, остальные разрешённые маршруты продолжают работать. Проверить `ShopPolicyDrops=FIRING` в Prometheus; через 1–2 минуты после окончания попыток он вернётся в inactive. Все три правила и дашборд находятся в `shop/templates/` и `shop/dashboards/`, сторонние chart в репозиторий не копируются.
