# Мониторинг shop

Использую Prometheus, Grafana и Alertmanager из Лабы 2. Второй стек не
разворачивается. Чарт shop создаёт два ServiceMonitor, PrometheusRule и
ConfigMap с [дашбордом](../shop/dashboards/shop.json).

## Подключение к существующему стеку

В Лабе 2 установлен обычный Prometheus без Operator: сам он не читает CR.
Официальный чарт prometheus-operator-crds 32.0.2 устанавливает только нужные
определения ServiceMonitor и PrometheusRule. `scripts/sync-monitoring.py`
читает их, преобразует в настройки прежних Helm releases Prometheus 29.38.1
и Grafana 10.5.15, сохраняя jobs, правила, datasource и RED-дашборд Лабы 2.

ServiceMonitor выбирает Service по меткам и именованному порту http.
Prometheus обнаруживает endpoints и собирает метрики каждой реплики раз в
15 секунд. Источник трёх алертов — PrometheusRule. Адаптер проверяет правила
через promtool, затем сверяет действующие правила Prometheus и дашборд Grafana
через API. Неизменившиеся настройки не создают новых Helm-ревизий.

Установка приложения уже включает синхронизацию. Для обновления и rollback
используется `platform/manage-shop.sh`; после прямого изменения CR или вызова
Helm адаптер нужно запустить явно:

```bash
python3 lecture-3-kubernetes-control-plane/scripts/sync-monitoring.py --context kind-lab2
```

Это одноразовый адаптер с поддержкой используемых полей CR, а не постоянно
работающий контроллер. Изменения endpoints Prometheus обнаруживает сам.

## Дашборд и алерты

В папке Labs существующей Grafana доступен `Shop — API и worker`, UID
`shop-platform`. Восемь панелей показывают доступные scrape-цели, firing
alerts, RPS, долю 5xx, p95, скорость обработки и возраст успешного опроса БД.
Из пользовательских RED-запросов исключён /health. p95 без трафика и heartbeat
при отсутствии всех worker могут показывать No data; это не нулевое значение.

| Алерт | Условие и причина |
| --- | --- |
| `ShopApiNoHealthyTargets` | Ни одной доступной scrape-цели API или исчезновение всех рядов up в течение 30 секунд. Проверить Pod, Service, /metrics, затем пользовательскую доступность. |
| `ShopApiHighErrorRate` | Более 5% ответов 5xx за 2 минуты при минимум 20 пользовательских запросах, условие держится 30 секунд. Выявляет ошибки API и зависимость от БД; probes исключены. |
| `ShopWorkerStalled` | Последний успешный опрос БД любым worker старше 30 секунд либо метрики всех worker отсутствуют; условие держится ещё 30 секунд. Выявляет остановку обработки при работающем API. |

## Проверка firing

В одном терминале сохранить исходное число worker и остановить обработку:

```bash
worker_replicas=$(kubectl --context kind-lab2 -n shop get deployment shop-worker -o jsonpath='{.spec.replicas}')
kubectl --context kind-lab2 -n shop scale deployment/shop-worker --replicas=0
```

Дождаться ShopWorkerStalled в firing в Prometheus и его получения Alertmanager.
Затем в том же терминале вернуть исходное число реплик:

```bash
kubectl --context kind-lab2 -n shop scale deployment/shop-worker --replicas="$worker_replicas"
kubectl --context kind-lab2 -n shop rollout status deployment/shop-worker
```

На проведённом эксперименте API продолжал отвечать, заказ ждал обработки,
после восстановления обработался, цели вернулись в UP и алерт исчез.
[Результаты и скриншоты](../REPORT.md).

Для просмотра интерфейсов в отдельных терминалах:

```bash
kubectl --context kind-lab2 -n monitoring port-forward svc/prometheus-server 9090:80
kubectl --context kind-lab2 -n monitoring port-forward svc/grafana 3000:80
kubectl --context kind-lab2 -n monitoring port-forward svc/alertmanager 9093:9093
```

Prometheus: http://localhost:9090/alerts, Grafana:
http://localhost:3000/d/shop-platform, Alertmanager: http://localhost:9093.
Вход в Grafana тот же, что в Лабе 2.
