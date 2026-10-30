# Helm-чарт shop

Чарт создаёт API (3 реплики), worker (2 реплики), PostgreSQL через CloudNativePG,
объекты мониторинга и дашборд. Результаты экспериментов и скриншоты находятся
в [отчёте](../REPORT.md).

## Установка

Нужен работающий kind-кластер `lab2` со стеком мониторинга из Лабы 2:
Prometheus 29.38.1, Grafana 10.5.15 и Alertmanager. Из корня репозитория:

```bash
bash lecture-3-kubernetes-control-plane/platform/install-kyverno.sh
python3 lecture-3-kubernetes-control-plane/policies/verify.py
bash lecture-3-kubernetes-control-plane/platform/install-cnpg.sh
bash lecture-3-kubernetes-control-plane/platform/install-shop.sh
kubectl --context kind-lab2 get pods,svc,cluster -n shop
```

Политики устанавливаются раньше приложения. Оператор нужен уже при первом
запуске: API и worker используют PostgreSQL. Скрипты собирают образы,
загружают их в kind, проверяют манифесты и устанавливают release `shop`.
Для другого кластера задаются `KIND_CLUSTER` и при необходимости `KUBE_CONTEXT`.

Использованы официальные чарты Kyverno 3.9.2 (v1.19.2), CloudNativePG 0.29.1
(1.30.1) и prometheus-operator-crds 32.0.2. В репозитории только собственные
values: сторонние шаблоны не копируются. Настройки upstream можно посмотреть
через `helm show values <repo/chart> --version <version>`.

Chart — пакет из Chart.yaml, values.yaml и templates/. Helm подставляет
values в шаблоны и применяет обычные Kubernetes-объекты; результат показывает
`helm template`. Установленная копия называется release, её ревизии хранятся
в Secret namespace и позволяют выполнить rollback. Values объединяются в
порядке defaults → файлы `-f` → `--set`, последнее значение имеет приоритет.

```bash
shop_node_ip=$(docker inspect -f '{{(index .NetworkSettings.Networks "kind").IPAddress}}' lab2-control-plane)
shop_url="http://$shop_node_ip:30080"
curl -fsS "$shop_url/health"
curl -fsS "$shop_url/orders"
```

## Настройки и обновления

В `values.yaml` задаются replicas, образы, ресурсы, хранилище и мониторинг.
Все Pod соответствуют [политикам](../policies/README.md). DATABASE_URL берётся
из Secret, созданного CloudNativePG. Startup-проба ждёт запуска сервера;
readiness и liveness обращаются к `/health`. У worker ошибки БД не ломают
liveness: успешные опросы отдельно проверяют `/ready` и heartbeat-метрика.

Обновление и откат выполняются общей командой, которая также синхронизирует
существующий мониторинг и проверяет реально загруженные настройки:

```bash
bash lecture-3-kubernetes-control-plane/platform/manage-shop.sh upgrade
# N — успешная ревизия из helm history shop -n shop:
bash lecture-3-kubernetes-control-plane/platform/manage-shop.sh rollback N
```

Можно передать дополнительные `-f` и `--set`. Даже failed rollout может
применить изменения PrometheusRule, поэтому синхронизация выполняется и при
ошибке Helm; команда сохраняет неуспешный результат, автоматического отката нет.

## Reconciliation и rolling update

Удаление API Pod привело к созданию замены с новым UID. Изменение
`api.replicas` в values с 3 на 4 и upgrade дали 4/4; затем вернул 3.
Поддерживает replicas контроллер Kubernetes, Helm только меняет spec.

При смене API 1.0.0 → 1.1.0 `maxSurge: 1`, `maxUnavailable: 0` и
`minReadySeconds: 5` позволили заменять реплики последовательно, сохраняя
минимум три готовые. Наблюдал Service через NodePort, поскольку port-forward
выбирает один Pod и может оборваться при его завершении. Получилось 282
запроса без ошибок; [исходное наблюдение](../evidence/02-rolling.txt).

Для повтора нужно сначала установить tag 1.0.0, затем изменить его на 1.1.0
и выполнить upgrade. В другом терминале можно опрашивать Service:

```bash
while true; do
  curl -fsS --max-time 2 "$shop_url/health"
  printf '\n'
  sleep 0.1
done
```

С `api.healthFail: true` новая реплика отвечала 503 на readiness и не попадала
в готовые endpoints; три старые оставались доступны. Rollout завершился
`Progress deadline exceeded`, 669 запросов прошли без ошибок. После явного
rollback — ещё 82 успешных запроса. [Состояние сломанного Pod](../evidence/02-broken-state.txt).
После эксперимента восстановил `healthFail: false` и в values.

## Оператор и отказ control plane

CloudNativePG управляет PostgreSQL через объект `Cluster`. В spec указаны
желаемые instances, образ и storage, в status — readyInstances, primary и
состояние БД. При удалении Pod оператор создал новый, подключив прежний PVC:
данные сохранились, восстановление заняло 12,57 секунды. Одна реплика БД
означает временные 503 у операций с заказами во время восстановления.

Оператор и kube-controller-manager используют reconciliation через API.
Controller-manager содержит встроенные контроллеры общих объектов, например
Deployment и ReplicaSet. Оператор устанавливается отдельно, расширяет API
через CRD и знает особенности PostgreSQL. CloudNativePG управляет Pod
непосредственно, без StatefulSet; Helm не выполняет постоянную сверку БД.

Для проверки control plane временно вынес static Pod-манифест kube-apiserver
из `/etc/kubernetes/manifests`, оставив ноду, kubelet и etcd работающими.
Через crictl подтвердил остановку контейнера. Helm upgrade и kubectl apply
не проходили, но существующий NodePort, API, worker и PostgreSQL работали:
заказ создался и обработался без API-сервера. После возврата манифеста
`/readyz` ответил ok и управляющие операции снова прошли.

[Мониторинг и обоснование трёх алертов](../monitoring/README.md).
