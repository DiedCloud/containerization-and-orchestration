# Воспроизведение лабораторной 4

Результаты и объяснения — в [REPORT.md](REPORT.md). `README.md` содержит исходный текст лекции. Все команды ниже выполняются из каталога этой лабораторной.

## Основа стенда

Нужен работающий `kind-lab2` из Лаб 2–3: Prometheus/Grafana/Alertmanager, Kyverno с guardrails, CloudNativePG, namespace `shop` и PostgreSQL на PVC. Код API и worker используется из `../lecture-3-kubernetes-control-plane/services/`. Эта работа обновляет существующий shop, не пересоздаёт его базу.

Инструменты: Docker, kind, kubectl, Helm 4, Python 3, k6 2.3.0. Для krr 1.31.1 и построения графиков нужен Python 3.12 с зависимостями krr. Площадка использована с 16 логическими CPU; `restore-capacity.sh` резервирует 12 CPU на control-plane и 14 на worker, оставляя 4 и 2 соответственно. На другом хосте эти резервы нужно пересчитать.

```bash
kubectl config use-context kind-lab2
kubectl get nodes
# Только если кластер пока состоит из одного lab2-control-plane:
python3 scripts/add-worker.py
```

Скрипт добавляет `lab2-worker` через kubeadm, сохраняя существующий кластер. В итоге должно быть строго две Ready-ноды.

## Образы и развёртывание

```bash
docker build --build-arg APP_VERSION=1.1.0 -t docker.io/library/shop:1.1.0 ../lecture-3-kubernetes-control-plane/services
docker build --build-arg APP_VERSION=1.1.1 -t docker.io/library/shop:1.1.1 ../lecture-3-kubernetes-control-plane/services
docker build -t docker.io/library/shop-batch:4.0.0 batch

docker pull ghcr.io/cloudnative-pg/cloudnative-pg:1.30.1
docker pull ghcr.io/cloudnative-pg/postgresql:17.7
kind load docker-image --name lab2 \
  docker.io/library/shop:1.1.0 docker.io/library/shop:1.1.1 \
  docker.io/library/shop-batch:4.0.0 \
  ghcr.io/cloudnative-pg/cloudnative-pg:1.30.1 \
  ghcr.io/cloudnative-pg/postgresql:17.7

helm lint shop
bash scripts/upgrade.sh --wait --timeout 5m
kubectl -n shop wait --for=condition=Ready cluster/shop-postgres --timeout=180s
bash scripts/sync-monitoring.sh
kubectl -n shop get pods -o wide
```

При ImagePullBackOff у DaemonSet новой ноды аналогично загрузить образы Alloy и node-exporter из values Лабы 2. Сторонние Helm chart не копируются: используются существующие releases и адаптер мониторинга Лабы 3. Версии Prometheus chart 29.38.1, Grafana chart 10.5.15; адаптер сохраняет их остальные настройки и проверяет загрузку правил и дашборда.

Chart содержит финальные ресурсы из [отчёта krr](evidence/krr.json). Все экспериментальные overrides применяются через Helm. Вызов `upgrade.sh` без дополнительных файлов возвращает рабочие defaults, включая две API и одну batch-реплику. Флаг `--wait` в скрипте преобразуется в Helm 4 `--wait=legacy`; состояние CNPG проверяется отдельно.

## Нагрузка и интерфейсы

```bash
mkdir -p results
# Узнать IP control-plane, не полагаясь на адрес конкретного компьютера:
docker inspect lab2-control-plane --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
```

В отдельном терминале запустить нагрузку, подставив найденный IP:

```bash
k6 run -e BASE_URL=http://172.20.0.2:30080 -e DURATION=10m \
  --summary-export results/load-summary.json \
  --out json=results/load.json load.js
```

По умолчанию RATE=10 заказов/с; DURATION и RATE меняются через `-e`. k6 проверяет HTTP 201, ID заказа, p95<300 мс, ошибки<1%, отсутствие dropped iterations. Прогон с SIGINT отмечается как прерванный, даже если накопленные метрики хорошие.

В двух других терминалах:

```bash
kubectl -n monitoring port-forward svc/prometheus-server 9090:80
```

```bash
kubectl -n monitoring port-forward svc/grafana 3001:80
```

Prometheus Alerts: `http://127.0.0.1:9090/alerts`. Grafana: `http://127.0.0.1:3001/d/shop-resources`, вход от Лабы 2. При перезапуске kubelet port-forward может завершиться — нужно запустить его заново. В Grafana выбрать Last 15 minutes и обновление 5s.

## krr и сверка ресурсов

Обычный krr не обнаруживает CNPG Cluster. `krr-cnpg.py` расширяет discovery по настоящему Cluster и его Pod, не создавая объектов в Kubernetes. Алгоритм и округление upstream не меняются; для поддержки вида Cluster адаптер расширяет локальную модель в checkout krr.

```bash
mkdir -p .tools
git clone --depth 1 --branch v1.31.1 https://github.com/robusta-dev/krr.git .tools/krr
python3.12 -m venv .tools/venv
.tools/venv/bin/pip install -r .tools/krr/requirements.txt
```

Сначала дать Prometheus собрать данные под нагрузкой. Для профилирования использовались RATE=30 и временный запас ресурсов:

```bash
bash scripts/upgrade.sh --wait --timeout 5m \
  --set api.resources.requests.cpu=500m --set api.resources.limits.cpu=500m \
  --set api.resources.requests.memory=256Mi --set api.resources.limits.memory=256Mi \
  --set postgres.resources.requests.cpu=1 --set postgres.resources.limits.cpu=1 \
  --set postgres.resources.requests.memory=256Mi --set postgres.resources.limits.memory=256Mi
```

После изменения ресурсов дождаться Ready PostgreSQL. Нагрузка для определения ресурсов и нагрузка SLA — разные режимы: SLA заявлен для 10 заказов/с. Запуск krr, пока Prometheus port-forward работает:

```bash
(cd .tools/krr && ../venv/bin/python ../../scripts/krr-cnpg.py simple-limit \
  -c kind-lab2 -n shop -p http://127.0.0.1:9090 \
  --history_duration 1 --timeframe_duration 1 --points_required 20 \
  --cpu_request 100 --cpu_limit 100 --memory_buffer_percentage 100 \
  -f json --fileoutput ../../results/krr.json)
```

Для таблицы заменить `-f json` на `-f table` и убрать `--fileoutput`. Новые рекомендации зависят от нагрузки и истории; сохранённый результат в evidence не перезаписывается. Воспроизведение приложенного профиля использует готовые значения в `shop/values.yaml`; для нового профиля перенести новые рекомендации в values и сделать Helm upgrade. CPU и память API/PostgreSQL должны иметь requests=limits. Worker остаётся Burstable, его limits не должны быть ниже новых requests.

```bash
.tools/venv/bin/python scripts/verify.py
bash scripts/upgrade.sh --wait --timeout 5m
kubectl -n shop wait --for=condition=Ready cluster/shop-postgres --timeout=180s
```

`verify.py` сверяет приложенные values с сохранённым krr JSON. После переноса новых рекомендаций для нового эксперимента сверять их с новым отчётом. У simple-limit минутное окно rate при 15-секундном scrape; короткая часовая история — лабораторное ограничение, предупреждение krr о ней сохранено.

## Pending, firing и preemption

Параллельно должна работать нагрузка 10 заказов/с. Сначала рабочий профиль, две готовые API и отсутствие завершающихся rollout:

```bash
python3 scripts/experiment-capacity.py
bash scripts/upgrade.sh -f experiments/06-fill.yaml
kubectl -n shop get pods -o wide
kubectl -n shop get events --field-selector reason=FailedScheduling
```

Скрипт рассчитывает резервы kubelet с учётом requests инфраструктуры; оставляет место двум batch по 500m на каждой ноде и меньше свободного CPU, чем нужно новому API. Batch увеличивается до 8 реплик, часть остаётся Pending с Insufficient cpu. **Не использовать --wait для заведомо невмещающегося batch.**

Дождаться ShopBatchUnschedulable в Firing, затем создать высокоприоритетных кандидатов:

```bash
bash scripts/upgrade.sh -f experiments/06-fill.yaml -f experiments/06-preemption.yaml
kubectl -n shop rollout status deployment/shop-api --timeout=180s
kubectl -n shop get pods -l app.kubernetes.io/name=api -o wide
kubectl -n shop get events --field-selector reason=Preempted
```

Ожидаются четыре готовые API и Preempted by pod для batch. На дашборде проверить p95, ошибки и RPS заказов. После наблюдения вернуть две API и обычный batch:

```bash
bash scripts/upgrade.sh --wait --timeout 5m
```

## MemoryPressure и eviction

В отдельном терминале до включения нагрузки памяти:

```bash
kubectl get node lab2-worker -w \
  -o custom-columns='NODE:.metadata.name,MEMORY_PRESSURE:.status.conditions[?(@.type=="MemoryPressure")].status'
```

В основном терминале:

```bash
LAB4_THRESHOLD=$(
  kubectl get --raw /api/v1/nodes/lab2-worker/proxy/stats/summary |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["node"]["memory"]["availableBytes"] // 1048576 - 384)'
)
python3 scripts/node-resources.py --memory-threshold "${LAB4_THRESHOLD}Mi"
bash scripts/upgrade.sh -f experiments/07-memory.yaml

kubectl -n shop get events --field-selector reason=Evicted
kubectl -n shop get pods \
  -o custom-columns='NAME:.metadata.name,QOS:.status.qosClass,REASON:.status.reason,RESTARTS:.status.containerStatuses[0].restartCount,MESSAGE:.status.message'
```

Дождаться MemoryPressure=True и свежего Evicted batch (обычно десятки секунд). Batch потребляет выше request=96Mi, но ниже limit=1Gi; API/PostgreSQL сохраняют Guaranteed и не перезапускаются. В стандартной колонке STATUS может быть Error — смотреть Pod reason и сообщение о нехватке памяти. Порог специально поднят для ограниченного опыта на kind, а не для исчерпания всей физической памяти хоста.

После наблюдения снять профиль:

```bash
python3 scripts/node-resources.py --memory-threshold 100Mi
bash scripts/upgrade.sh --wait --timeout 5m
```

## Контроль OOM и завершение

```bash
bash scripts/upgrade.sh -f experiments/07-oom-control.yaml
# Через 10–20 секунд, при необходимости повторить:
kubectl -n shop get pods -l app=shop-batch \
  -o custom-columns='NAME:.metadata.name,RESTARTS:.status.containerStatuses[0].restartCount,LAST_REASON:.status.containerStatuses[0].lastState.terminated.reason,MEMORY_LIMIT:.spec.containers[0].resources.limits.memory'
```

У нового batch ожидается OOMKilled и увеличение restartCount при limit=128Mi. После этого обязательно восстановить рабочий профиль:

```bash
bash scripts/upgrade.sh --wait --timeout 5m
bash scripts/restore-capacity.sh
kubectl -n shop get pods -o wide
kubectl -n shop get cluster shop-postgres
```

Должны работать две разнесённые API, два worker, одна batch и здоровый PostgreSQL. Завершённые Evicted Pod могут оставаться в списке. Перенаправления портов при необходимости открыть заново.

## Данные и графики

В evidence оставлены отчёт krr, три k6 summary, данные десятисекундных окон, отметки событий и два клиентских графика. Скриншоты лежат в screenshots. Новые временные результаты записывать в игнорируемый `results/`.

Построить графики из приложенных окон:

```bash
.tools/venv/bin/python scripts/plot-sla.py cpu
.tools/venv/bin/python scripts/plot-sla.py memory
```

Обработать собственный сырой поток k6:

```bash
.tools/venv/bin/python scripts/plot-sla.py cpu --input results/load.json
```

Графики и рассчитанные окна появятся в results. Для новых отметок времени можно передать `--events results/events.json`: список объектов `{"phase": "batch-preempted", "time": 1793395660}` с фактическим Unix-временем событий. Оценивать SLA по завершённому k6 summary и графикам, не переносить числа из приложенных измерений на новый прогон автоматически.
