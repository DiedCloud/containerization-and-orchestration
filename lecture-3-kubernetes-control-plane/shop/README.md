# Часть 2 — Helm-чарт shop

Собственный чарт создаёт Deployment и Service для API и worker. По умолчанию
это 3 и 2 реплики. PostgreSQL описан объектом `Cluster` CloudNativePG:
оператор установлен отдельно один раз на кластер. Это необходимая БД для
проверок API; эксперимент с восстановлением БД относится к части 3.

## Установка

Предполагается, что часть 1 выполнена и политики уже работают. Из корня
репозитория:

```bash
bash lecture-3-kubernetes-control-plane/platform/install-cnpg.sh
bash lecture-3-kubernetes-control-plane/platform/install-shop.sh
kubectl --context kind-lab2 get pods,svc -n shop
helm --kube-context kind-lab2 list -n shop
```

Оператор: официальный чарт `cnpg/cloudnative-pg` **0.29.1**, приложение
**1.30.1**. В репозитории только наш values-файл, upstream не копируется.
`helm show values cnpg/cloudnative-pg --version 0.29.1` показывает доступные
параметры. Образы предварительно загружаются в kind с хоста из-за обнаруженной
в части 1 проблемы DNS ноды.

Скрипт приложения собирает образы 1.0.0 и 1.1.0 с разным `APP_VERSION`,
загружает их в kind, выполняет `helm lint`, server dry-run манифестов и
установку release `shop`. Заголовок `X-Shop-Version` позволяет отличать
версии в HTTP-ответах. При первом запуске все объекты прошли политики,
готовы 3 API, 2 worker и 1 PostgreSQL.

API доступен через NodePort 30080 на IP ноды kind:

```bash
shop_node_ip=$(docker inspect -f '{{(index .NetworkSettings.Networks "kind").IPAddress}}' lab2-control-plane)
curl -i "http://$shop_node_ip:30080/health"
curl -s "http://$shop_node_ip:30080/orders" | python3 -m json.tool
```

На текущем стенде это `http://172.20.0.2:30080`. Новый Service распределяет
запросы между готовыми Pod. Для проверки обновления используем именно его.
Обычный port-forward к Service выбирает один Pod, поэтому его завершение
может оборвать доступ независимо от готовности остальных реплик.

## Настройки и механизмы

- `api.replicas` / `worker.replicas` и отдельные `image.tag` читаются из
  `values.yaml`; обновление образа API не меняет worker.
- Все Pod имеют метку `app`, CPU/memory requests и limits. Privileged и
  пространства имён хоста выключены. Включены non-root, seccomp и read-only
  root filesystem. Service выбирает Pod по имени компонента и release.
- Readiness и liveness обращаются к `/health`. Readiness управляет допуском
  в Service; liveness перезапускает неработающий контейнер.
- TCP startup-проба ждёт открытия сервера после подключения к БД и создания
  схемы. До этого liveness не мешает первому запуску. Она не скрывает
  `HEALTH_FAIL`: сервер с этой переменной слушает порт, а HTTP-пробы дают 503.
- `maxSurge: 1`, `maxUnavailable: 0`, `minReadySeconds: 5`: новая реплика
  добавляется по одной, старая убирается после готовности новой и выдержки
  времени. `preStop` даёт 3 секунды на распространение изменения endpoints,
  затем uvicorn получает SIGTERM и завершает активные запросы.
- Завершающиеся Pod могут кратковременно увеличивать общее число строк в
  `kubectl get pods`. При проверке surge считаем активные Pod отдельно от
  `Terminating`.
- CloudNativePG создаёт Secret `shop-postgres-app`; `DATABASE_URL` берётся из
  его ключа `uri`. Пароль не попадает в values. База использует PVC на 1 GiB,
  а `inheritedMetadata` и `resources` обеспечивают выполнение политик и для
  создаваемых оператором Pod.

## Проверки reconciliation и обновления

Сначала проверил 50 параллельных заказов уже в Kubernetes: все сохранились
и обработались, в `processed_by` встретились оба worker.

Удалил один API Pod через `kubectl delete pod`. ReplicaSet создал замену с
новым UID и вернулся к трём готовым репликам. Затем изменил `api.replicas`
в `values.yaml` с 3 на 4 и выполнил `helm upgrade`: Deployment стал `4/4`.
Вернул 3 тем же способом. Helm меняет желаемое состояние; поддерживает его
уже Kubernetes, даже когда команда Helm завершилась.

Для rolling update изменил `api.image.tag` в `values.yaml` с 1.0.0 на 1.1.0.
Во время `helm upgrade --wait` скрипт `scripts/observe-rollout.py` делал
запросы к Service примерно каждые 100 мс и опрашивал Pod каждые 500 мс.
Получилось **282 запроса, 0 ошибок**, в ответах видны обе версии. Готовых
API было не меньше 3, активных — не больше 4; снимки ReplicaSet показали
последовательную замену старых Pod.

Пример запуска наблюдения (путь output намеренно локальный и исключён из Git):

```bash
python3 lecture-3-kubernetes-control-plane/scripts/observe-rollout.py \
  --url http://172.20.0.2:30080 \
  --output lecture-3-kubernetes-control-plane/artifacts.local/rolling \
  -- helm upgrade shop lecture-3-kubernetes-control-plane/shop \
  --kube-context kind-lab2 -n shop \
  -f lecture-3-kubernetes-control-plane/shop/values.yaml --wait --timeout 2m
```

Для воспроизведения перехода нужно сначала установить версию 1.0.0, затем
поменять tag на 1.1.0. Повторный upgrade с теми же values не заменяет Pod.

Смысл проверки сломанного обновления: `api.healthFail: true` передаёт
`HEALTH_FAIL=true` в новую реплику. Старая рабочая ReplicaSet сохраняется,
пока новая не проходит readiness. Не используем автоматический откат: после
ошибки ожидания выполняем явный `helm rollback` на успешную ревизию.

Проверка выполнена: Helm остановил обновление с `Progress deadline exceeded`.
Одна новая реплика оставалась `0/1`, readiness возвращала 503, три рабочие
реплики сохранились. EndpointSlice подтвердил, что готовые endpoints
принадлежат только этим трём Pod. **669 запросов, 0 ошибок**. Liveness
перезапускала сломанный контейнер, но это не могло исправить его конфигурацию.

Выполнил `helm rollback shop 4 -n shop --wait`. Появилась ревизия 6 со
статусом `deployed` и настройками ревизии 4. Во время отката — **82 запроса,
0 ошибок**. Все 50 заказов сохранились; новый заказ после отката тоже
обработан. Итог: API 3/3 с образом 1.1.0 и `HEALTH_FAIL=false`, worker 2/2
с образом 1.0.0, PostgreSQL Ready. В файле values также восстановлен
`api.healthFail: false`, чтобы следующий upgrade не повторил сбой.

Между экспериментом и продолжением работы нода kind перезапустилась
(`Node Rebooted`); поэтому в итоговом списке у исправных контейнеров тоже
есть по одному restart. Данные на PVC сохранились. Нулевые ошибки HTTP
относятся к записанным интервалам наблюдения, а не ко всему перерыву.

## Скриншоты части 2

Состояние во время экспериментов сохранено локально, повторять сломанное
обновление для снимков не требуется:

```bash
cat lecture-3-kubernetes-control-plane/artifacts.local/02-reconciliation.txt
cat lecture-3-kubernetes-control-plane/artifacts.local/02-scale-up.txt
cat lecture-3-kubernetes-control-plane/artifacts.local/02-summary.txt
cat lecture-3-kubernetes-control-plane/artifacts.local/02-broken-state.txt
kubectl --context kind-lab2 get pods,svc -n shop
helm --kube-context kind-lab2 history shop -n shop
```

Нужны: замена удалённого Pod, API 4/4 после масштабирования, последовательность
rolling update и ноль ошибок, новая неготовая реплика с readiness=503,
успешный rollback и готовый стенд. Папка `artifacts.local` исключена из Git;
в отчёт добавляем выбранные скриншоты и краткие результаты.

## Часть 3 — PostgreSQL через оператор

CloudNativePG установлен отдельным release `cnpg` в `cnpg-system`, один раз
на кластер. Наш чарт создаёт `Cluster/shop-postgres`. CRD
`clusters.postgresql.cnpg.io` регистрирует этот тип в API; объект Cluster
описывает PostgreSQL, а не новый Kubernetes-кластер.

Удалил `shop-postgres-1` через `kubectl delete pod`. В его `ownerReferences`
указан непосредственно `Cluster/shop-postgres`: CloudNativePG использует
собственный Pod controller, без StatefulSet и ReplicaSet.

| Проверка | Наблюдаемый результат |
| --- | --- |
| UID старого Pod | `62dda54e-3161-4868-a800-53c42d07f731` |
| UID нового Pod | `4fe3d8cf-6805-4c42-b699-810c20d51094` |
| Восстановление | 12,57 секунды до готовности Pod и Cluster |
| Хранилище | Прежний PVC `shop-postgres-1`, тот же UID PVC и PV |
| Данные | Все 51 прежний заказ полностью совпали до/после |
| Новая запись | Заказ №52 создался и обработался worker |
| `/health` API | 79 ответов 200 |
| `/orders` | 20 ответов 200 и 28 ответов 503 |

Одна реплика PostgreSQL означает временную недоступность операций с БД
при удалении её Pod. После восстановления они возобновились. API-процесс
оставался здоровым: его `/health` намеренно не зависит от PostgreSQL.

В `kubectl get cluster shop-postgres -n shop -o yaml` сравнил:

| Раздел | Поля и смысл |
| --- | --- |
| `spec` | Желаемое: `instances: 1`, образ 17.7, `bootstrap.initdb` с БД/владельцем `shop`, `storage.size: 1Gi`, `storageClass: standard` |
| `status` | Наблюдаемое: `instances: 1`, `readyInstances: 1`, `currentPrimary: shop-postgres-1`, `phase: Cluster in healthy state`, условие `Ready=True` |

`spec` отправляется через Helm, `status` заполняет оператор. В эксперименте
UID и spec Cluster не менялись: удаление дочернего Pod не отменило желаемую
БД. Новый Pod подключил прежний PVC; повторная инициализация пустой БД не нужна.

### Оператор и kube-controller-manager

Оба используют reconciliation через API-сервер. `kube-controller-manager`
входит в control plane и запускает встроенные контроллеры общих объектов,
например Deployment и ReplicaSet. Они не знают особенностей PostgreSQL.
Оператор установлен отдельно, расширяет API через CRD и содержит логику
эксплуатации конкретной системы. CloudNativePG управляет Pod, PVC,
primary/replica и конфигурацией PostgreSQL. Helm устанавливает объекты,
а постоянное восстановление выполняет оператор.

### Проверка и скриншоты

Результаты доступны без повторного удаления базы:

```bash
cat lecture-3-kubernetes-control-plane/artifacts.local/03-postgres/summary.txt
kubectl --context kind-lab2 get pods,pvc,cluster -n shop
kubectl --context kind-lab2 get cluster shop-postgres -n shop -o yaml
```

Нужны снимки разных UID Pod, неизменного PVC, сохранности заказов и готовой
БД, а также полей `spec` и `status`. Полные YAML до/после и CSV HTTP-запросов
сохранены локально в исключённой из Git папке `artifacts.local/03-postgres`.

Для повторения эксперимента с временной недоступностью БД:

```bash
python3 lecture-3-kubernetes-control-plane/scripts/check-postgres-recovery.py
```

Скрипт фиксирует текущее число заказов и UID, удаляет только Pod, проверяет
прежнее хранилище и данные и создаёт один проверочный заказ. Повторный запуск
обновляет локальные результаты.

## Часть 4 — отказ API-сервера

Остановил именно `kube-apiserver` внутри работающей kind-ноды. Это static
Pod: kubelet читает его манифест из `/etc/kubernetes/manifests`. Временно
перенёс файл в соседний каталог и через `crictl` дождался отсутствия
работающего контейнера API-сервера. Kubelet, etcd и приложения не останавливал.
Простое завершение процесса было бы недостаточно: kubelet запустил бы его
снова по оставшемуся манифесту.

Управление и обслуживание запросов проверял разными путями:

| Проверка при выключенном API-сервере | Результат |
| --- | --- |
| `kubectl apply` тестового ConfigMap | exit 1, `context deadline exceeded` / `EOF` |
| `helm upgrade` с попыткой увеличить API до 4 реплик | exit 1, `kubernetes cluster unreachable` / `EOF` |
| `/health` через NodePort | 119 ответов 200, 0 ошибок |
| `/orders` через NodePort | 110 ответов 200, 0 ошибок |
| Создание и обработка заказа | Заказ №53 создан и обработан worker при выключенном API-сервере |

Подтверждённый интервал без API-сервера — 25,14 секунды. С учётом этапов
остановки и восстановления получилось 301 успешное обращение к `/health`
и 280 к `/orders`, тоже без ошибок. Трафик шёл через существующий NodePort,
без port-forward, который зависит от API-сервера.

Контейнеры продолжали работать под контролем kubelet; существующие сетевые
правила Service продолжали направлять запросы к API. Сам API и worker
обращаются к PostgreSQL напрямую, а не через Kubernetes API. Поэтому
сохранился весь путь создания и обработки заказа. При этом контроллеры и
планировщик не могли получать и записывать новое состояние через API-сервер;
эксперимент не означает, что в этот момент можно развернуть новый сервис.

Вернул манифест в каталог kubelet, дождался `/readyz = ok` и проверил реальные
операции `kubectl apply/get/delete` на тестовом ConfigMap. Создание во время
отказа ничего не сохранило; после восстановления объект успешно создался и
был удалён. Все 6 Pod shop сохранили UID и счётчики перезапусков. Все 52
прежних заказа сохранились, новый обработанный заказ №53 остался в БД.
История Helm не изменилась: release `shop` остался на ревизии 6, API — 3/3.

Скрипт восстанавливает файл в `finally`; дополнительно отдельный процесс
внутри ноды вернёт его через 180 секунд, если основной скрипт прервётся.
Временный файл находится вне каталога static Pod: kubelet читает там все
не скрытые файлы, независимо от расширения.

Для скриншотов достаточно сохранённой сводки и текущего состояния:

```bash
cat lecture-3-kubernetes-control-plane/artifacts.local/04-control-plane/summary.txt
kubectl --context kind-lab2 get --raw /readyz
kubectl --context kind-lab2 get pods,cluster -n shop
```

На снимке нужны ошибки управляющих команд, успешные запросы и обработка
заказа во время отказа, затем восстановленная управляемость. Подробные
ошибки команд и CSV находятся в той же локальной папке, исключённой из Git.
Повторный запуск самого эксперимента:

```bash
python3 lecture-3-kubernetes-control-plane/scripts/check-control-plane.py
```

Он временно останавливает API-сервер и добавляет один проверочный заказ,
а локальные результаты перезаписывает.

## Часть 5 — мониторинг

В чарт добавлены два `ServiceMonitor`, `PrometheusRule` с тремя алертами и
ConfigMap дашборда. Используется существующий стек Лабы 2. Обычный Prometheus
не читает CRD напрямую: наш одноразовый адаптер читает объекты из Kubernetes
и обновляет его Helm values, сохраняя старые jobs и правила. После изменения
мониторинга требуется повторная синхронизация.

[Установка, обоснование трёх алертов и проверка firing](../monitoring/README.md).

Документация: [жизненный цикл static Pod](https://kubernetes.io/docs/tasks/configure-pod-container/static-pod/),
[собственный Pod controller CloudNativePG](https://cloudnative-pg.io/docs/current/controller/),
[kube-controller-manager](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-controller-manager/),
[Deployment и rolling update](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/),
[CloudNativePG](https://github.com/cloudnative-pg/cloudnative-pg),
[официальный Helm-чарт оператора](https://github.com/cloudnative-pg/charts/tree/main/charts/cloudnative-pg).
