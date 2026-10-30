# Лабораторная 4 — SLA критического пути под перегрузкой

Развиваю собственный chart `shop` из Лабы 3; его версия 0.2.0 находится в `shop/`, чтобы сохранить результат предыдущей работы. Использую существующие PostgreSQL, guardrails и мониторинг.

## 1. Разнесение

Выбрал `topologySpreadConstraints`: `maxSkew: 1`, `DoNotSchedule`, `minDomains: 2`, topologyKey `kubernetes.io/hostname`. Две реплики API должны оказаться на двух нодах. При потере домена minDomains не позволит новой реплике занять оставшийся домен сверх разрешённого перекоса. Это осознанный выбор строгого разнесения: существующая реплика продолжает работу, а замена ждёт восстановления второй ноды.

`podAntiAffinity` запрещает соседство реплик на одном hostname вообще. При двух нодах третья реплика с required anti-affinity останется Pending. Spread ограничивает разницу числа реплик и допускает распределение 2:1. Обе реализации включаются через `placement.mechanism`, конфигурация API остаётся частью Helm.

Chart — пакет с Chart.yaml, templates/ и values.yaml. Helm подставляет значения в шаблоны и применяет обычные Kubernetes-объекты; результат виден в `helm template`. Установленный экземпляр — release; ревизии хранятся в Secret и позволяют rollback. Значения объединяются в порядке defaults → файлы -f → --set, последнее значение побеждает. Сторонние chart не копирую: использую существующие releases с закреплёнными версиями и своими overrides.

## 2–3. Стенд и ресурсы

В кластере строго две ноды: `lab2-control-plane` и `lab2-worker`. Вторую присоединил через kubeadm, потому что kind не поддерживает добавление worker командой `kind create cluster` к уже созданному кластеру. Это сохранило PVC PostgreSQL и существующие releases Лаб 2–3. Скрипт: `scripts/add-worker.py`. Для нового независимого стенда можно сразу создать kind с одним control-plane и одним worker; существующий кластер удалять не нужно.

Batch собран из `batch/`, образ `docker.io/library/shop-batch:4.0.0` загружен через `kind load docker-image --name lab2`. У него есть app label, CPU/memory requests и limits, запуск без root/privileged/host namespaces. Исключений из Kyverno для batch нет.

| Компонент | Изначальные requests CPU / RAM | KRR requests CPU / RAM | Финальные limits CPU / RAM |
|---|---|---|---|
| api | 50m / 64Mi | 486m / 131Mi | 486m / 131Mi |
| worker | 25m / 64Mi | 217m / 100Mi | 250m / 128Mi |
| postgres | 100m / 128Mi | 870m / 212Mi | 870m / 212Mi |

Первоначальная догадка недооценивала нагрузку при создании заказов, обработке очереди и работе instance manager PostgreSQL. Первый simple p99 предложил 61m/100Mi API и 156m/100Mi PostgreSQL; эти значения нельзя было без проверки превратить в жёсткие CPU limits: появились throttling, сбои probes/lease CNPG и нарушение SLA. После профилирования с запасом ресурсов применил штатный `simple-limit`: CPU request p100 = limit p100, memory max+100%. Это даёт запас на короткую историю и служебные процессы; абсолютные значения рассчитаны krr. Worker 100Mi упирается в стандартный минимальный порог, API/PostgreSQL получены из наблюдаемого максимума памяти. Первые неудачные результаты сохранены отдельно; итоговый JSON — `evidence/03-krr-final.json`. Подробности — `scripts/tooling.md`.

KRR v1.31.1 не обнаруживает CNPG Cluster. Read-only адаптер `scripts/krr-cnpg.py` добавляет реальный Cluster и его Pod в discovery. Формулы стратегии, PromQL loaders, округление и формат отчёта остались upstream. Это не фиктивный StatefulSet и не отдельный ручной расчёт PostgreSQL.

## 4–5. Размещение и защита

Фактический вывод `kubectl get pods -o wide`: `evidence/04-spread.txt`, итоговое состояние — `evidence/05-guarantees.txt`. Потеря одной ноды не удалит обе API-реплики. PostgreSQL при одной instance всё ещё является единственной точкой отказа: разнесение API не превращает базу в HA.

API и postgres: CPU/memory requests = limits из krr, PriorityClass `shop-critical` (100000). Batch: requests ниже limits, PriorityClass `shop-batch` (-1000), `preemptionPolicy: Never`. Последнее запрещает batch вытеснять других, но не защищает его самого от вытеснения.

PDB API: minAvailable=1; PostgreSQL: minAvailable=1 на primary, бюджет создаёт CNPG (`postgres.yaml`: enablePDB из values). Не создаю второй перекрывающий PDB. При одной БД drain через Eviction API будет блокироваться — это ожидаемо. PDB не предотвращает поломку ноды и kubelet eviction по нехватке памяти; при scheduler preemption бюджет учитывается best effort.

Почему одного приоритета недостаточно? Планировщик при preemption сравнивает priority и requests, а не QoS. Kubelet при MemoryPressure сначала смотрит, превышает ли Pod memory request, затем priority и величину превышения. Поэтому batch, использующий заметно больше request, является подходящей жертвой; Guaranteed при равных requests/limits оказывается лучше защищён. Гарантия не абсолютна: при исчерпании всех менее защищённых кандидатов пострадать может и критический путь.

## Повторное применение

Все изменения приложения — через chart, никаких разовых kubectl patch:

```bash
bash lecture-4-scheduling-resources/scripts/upgrade.sh --wait --timeout 4m
bash lecture-4-scheduling-resources/scripts/sync-monitoring.sh
```

Второй скрипт переводит ServiceMonitor/PrometheusRule в конфигурацию существующего обычного Prometheus Лабы 2. Он не Prometheus Operator: без адаптера CR сами не активируют scrape/alerts. Версии существующих chart закреплены: prometheus 29.38.1, grafana 10.5.15. Upstream chart не скопированы.

## 6. Pending и preemption

`experiments/06-fill.yaml` увеличивает batch до 8 реплик с requests=500m CPU; процесс реально использует около 20m. Скрипт `scripts/experiment-capacity.py` вычисляет reservations так, чтобы на каждой ноде после системных Pod и API осталось ровно два слота batch и меньше свободного CPU, чем требуется ещё одному API. Это воспроизводимо на хосте с 16 ядрами: менять физический CPU или подделывать usage не нужно. Настройки kubelet меняют площадку, параметры приложения по-прежнему задаёт только Helm.

```bash
python3 lecture-4-scheduling-resources/scripts/experiment-capacity.py
bash lecture-4-scheduling-resources/scripts/upgrade.sh -f lecture-4-scheduling-resources/experiments/06-fill.yaml
# Наблюдать Pending / FailedScheduling: Insufficient cpu.
bash lecture-4-scheduling-resources/scripts/upgrade.sh \
  -f lecture-4-scheduling-resources/experiments/06-fill.yaml \
  -f lecture-4-scheduling-resources/experiments/06-preemption.yaml
```

Последний файл увеличивает API с двух до четырёх реплик: высокоприоритетным новым Pod нужны занятые batch слоты. Само увеличение batch не вызывает вытеснение уже работающих API. Планировщику нужен новый высокоприоритетный кандидат — поэтому второй шаг необходим.

## 7. Eviction и OOMKilled

В kind memory eviction по умолчанию выключен. Для опыта на worker включаю `evictionHard.memory.available` с порогом, расположенным на 256Mi ниже текущего available из kubelet stats/summary. Batch постепенно выделяет 768Mi при собственном limit=1Gi. Так можно пересечь реальный порог kubelet без исчерпания всей памяти рабочего ноутбука; это специально завышенный лабораторный eviction threshold, а не физическая нехватка всех 24Gi хоста.

`experiments/07-memory.yaml` направляет два batch Pod на worker. При пересечении порога нужно смотреть статус Pod `Failed / Evicted`, сообщение kubelet `The node was low on resource: memory`, события `EvictionThresholdMet`/`Evicted` и состояние ноды `MemoryPressure=True`. Guaranteed API сохраняется. Даже у low-priority batch есть limit=1Gi: его убирает kubelet до достижения собственного лимита.

Отдельный контроль `experiments/07-oom-control.yaml`: после возврата обычного порога 100Mi batch пытается выделить 256Mi с limit=128Mi. Здесь ожидается `lastState.terminated.reason=OOMKilled` и рост restartCount внутри того же Pod. Evicted — решение kubelet об удалении всего Pod ради ноды; OOMKilled — kernel/cgroup убил контейнер по его собственному memory.max. PDB от этих двух ситуаций не защищает.

## 8–9. SLA и мониторинг

SLA этого стенда: при 10 POST /order в секунду p95 клиентской задержки <300 мс, доля HTTP-ошибок <1%, все успешные ответы содержат ID сохранённого заказа, dropped_iterations=0. Проверяется и штатный интервал, и отдельные интервалы CPU/preemption и MemoryPressure. Это ограниченный профиль нагрузки, не обещание для любого RPS. Время асинхронной обработки worker не входит в SLA синхронного пути api → postgres.

Дашборд `Shop — SLA под перегрузкой` (UID `shop-resources`) показывает p95, ошибки, RPS, доступность API, CPU/memory/throttling Pod, Pending/evicted batch, MemoryPressure и firing alerts. Клиентские результаты k6 включают сетевую задержку и недоступность до ответа API; графики приложения из Prometheus показывают серверную сторону. Для проверки SLA используем оба источника.

| Алерт | Почему он нужен |
|---|---|
| ShopOrderSLOBreach | p95 >300 мс или не-201 >1% за 2 минуты при >=20 запросов; предупреждает о реальном ухудшении критического пути. |
| ShopBatchUnschedulable | batch не может разместиться 30 секунд; показывает цену защиты API и нехватку ресурсов для аналитики. |
| ShopNodeMemoryPressure | MemoryPressure держится 30 секунд; сигнал уровня ноды, где нужно искать eviction и проверить критический путь. |

`ServiceMonitor` собирает API и worker каждые 15 секунд; node/cAdvisor/kube-state-metrics уже поступают из стека Лабы 2. Все три правила находятся в `shop/templates/prometheusrule.yaml`; JSON дашборда включён в chart как ConfigMap. Pending batch используется для воспроизводимого firing без намеренного отказа API.

Официальные описания механизмов: [node-pressure eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/), [приоритет и preemption](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/), [алгоритм KRR](https://github.com/robusta-dev/krr/tree/v1.31.1).

При обновлениях обнаружился дополнительный нюанс разнесения: если считать вместе старую и новую ReplicaSet, rolling update может оставить две финальные API-реплики на одной ноде — старые Pod временно уравновешивали распределение, а затем удалились. Поэтому добавил `matchLabelKeys: [pod-template-hash]`: планировщик сравнивает реплики одной ревизии отдельно. Ограничение влияет на размещение новых Pod, уже размещённые оно само не переселяет.

Для альтернативной required podAntiAffinity chart автоматически использует API rollingUpdate maxSurge=0/maxUnavailable=1. При двух занятых нодах surge-реплике негде разместиться: сначала освобождается один слот, при этом вторая API-реплика остаётся доступной. У выбранного topology spread остаётся обычный maxSurge=1/maxUnavailable=0.
