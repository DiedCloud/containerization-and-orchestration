# Часть 5 — мониторинг поверх Лабы 2

Использую прежние releases `prometheus`, `grafana` и `alertmanager` в
`monitoring`. Второго Prometheus и нового kube-prometheus-stack нет.
Установлен только официальный CRD-чарт
`prometheus-community/prometheus-operator-crds` **32.0.2** (v0.94.2), причём
включены лишь ServiceMonitor и PrometheusRule. Upstream-манифесты не копируются.

## Как подключены объекты чарта

Обычный Prometheus из Лабы 2 не читает эти CRD сам. Поэтому
`scripts/sync-monitoring.py` — явный одноразовый адаптер, а не Operator:

1. Читает два ServiceMonitor и PrometheusRule release `shop` из Kubernetes.
2. Преобразует matchLabels, namespaceSelector и HTTP endpoints в scrape jobs.
   В имени job остаётся источник, например `serviceMonitor/shop/shop-api/0`.
   ServiceMonitor выбирает Service по меткам и именованному порту `http`.
3. Копирует группы правил из PrometheusRule, проверяет их через `promtool`
   и добавляет к прежним правилам Лабы 2. Ручной второй копии алертов нет.
4. Делает upgrade прежнего Prometheus с `--reuse-values` и закреплённой
   версией **29.38.1**. Старые scrape jobs, правила и Alertmanager сохраняются.
5. Подключает ConfigMap `shop-dashboard`, созданный нашим чартом в
   `monitoring`, через нового file provider прежней Grafana **10.5.15**.
   Существующие datasource и RED-дашборд сохраняются.

Скрипт поддерживает используемое в этой лабе подмножество ServiceMonitor,
проверяет неподдерживаемые настройки и не является постоянно работающим
контроллером. После изменения CR нужно повторить синхронизацию. Изменения
Pod и endpoints обнаруживаются самим Prometheus автоматически.

Включение на уже работающем shop:

```bash
bash lecture-3-kubernetes-control-plane/platform/install-monitoring.sh
```

При установке с нуля `platform/install-shop.sh` также ставит CRD и запускает
адаптер. Предпосылка — работающий стек Лабы 2 и оператор PostgreSQL.
Сгенерированные overrides и резервные копии старых values хранятся только
в исключённой папке `artifacts.local/05-monitoring`.

## Метрики и дашборд

У API собираются счётчик запросов и гистограмма длительности, у worker —
обработанные заказы, ошибки и время последнего успешного опроса БД.
Scrape выполняется раз в 15 секунд с каждой реплики: **3 API + 2 worker**.

Дашборд [shop.json](../shop/dashboards/shop.json), UID `shop-platform`,
расположен в папке `Labs` существующей Grafana. Восемь панелей:
доступность API и worker, firing alerts, RPS, доля 5xx, p95, скорость обработки
заказов и возраст успешного опроса БД. В пользовательских RED-запросах
исключён `/health`, поэтому Kubernetes probes не занижают долю ошибок.
Доля ошибок использует единицу `percentunit`.

Отсутствующий heartbeat при нуле worker — отсутствие метрик, а не нулевая
задержка. Эта панель может показывать No data во время отказа; алерт учитывает
такой случай через `absent()`. p95 требует пользовательского трафика.

## Три алерта и причины

| Алерт | Условие | Зачем и что проверить |
| --- | --- | --- |
| `ShopApiNoHealthyTargets` | Ни одной доступной scrape-цели API, включая исчезновение всех рядов `up`, 30 секунд | Выявляет потерю наблюдаемости всего API. Проверить Pod, Service, `/metrics`, затем пользовательскую доступность. |
| `ShopApiHighErrorRate` | Более 5% ответов 5xx за 2 минуты при минимум 20 запросах, условие держится 30 секунд; `/health` исключён | Выявляет пользовательские ошибки, в том числе проблемы БД. Проверить логи API/PostgreSQL и последние изменения. |
| `ShopWorkerStalled` | Последний успешный опрос БД любым worker старше 30 секунд либо метрики всех worker отсутствуют; условие держится ещё 30 секунд | API может принимать заказы, но обработка остановится. Проверить реплики worker, логи и PostgreSQL. |

## Проверка firing и восстановления

```bash
python3 lecture-3-kubernetes-control-plane/scripts/check-monitoring.py
```

Скрипт проверяет реальные targets, правила, provisioned-дашборд и сохранность
мониторинга Лабы 2. Затем масштабирует worker в ноль, создаёт заказ и ждёт
`ShopWorkerStalled` в состоянии `firing` в Prometheus и появления алерта в
существующем Alertmanager. В `finally` возвращает 2 worker, проверяет обработку
заказа, восстановление пяти целей и исчезновение активных shop-алертов.
Управляемая Helm конфигурация worker остаётся равной двум репликам.

JSON реального firing-состояния, результаты PromQL и сводка сохраняются
локально. Для ручного просмотра во время проверки можно
задать `--hold-seconds 120`; затем восстановление продолжится автоматически.

## Интерфейсы и скриншоты

В отдельных терминалах:

```bash
kubectl -n monitoring port-forward svc/prometheus-server 9090:80
kubectl -n monitoring port-forward svc/grafana 3000:80
kubectl -n monitoring port-forward svc/alertmanager 9093:9093
```

Grafana: `http://localhost:3000/d/shop-platform`, вход как в Лабе 2.
Prometheus: `http://localhost:9090/targets` и `/alerts`.
Alertmanager: `http://localhost:9093`.

Для отчёта нужны дашборд, пять целей UP и реальное firing-состояние хотя бы
одного алерта. После эксперимента его сохранённые данные доступны через:

```bash
cat lecture-3-kubernetes-control-plane/artifacts.local/05-monitoring/summary.txt
cat lecture-3-kubernetes-control-plane/artifacts.local/05-monitoring/prometheus-firing.json
```

Источники: [ServiceMonitor и его выбор](https://prometheus-operator.dev/docs/platform/troubleshooting/),
[конфигурация Prometheus](https://prometheus.io/docs/prometheus/latest/configuration/configuration/),
[официальный CRD-чарт](https://github.com/prometheus-community/helm-charts/tree/main/charts/prometheus-operator-crds).
