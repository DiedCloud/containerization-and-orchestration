# Скриншоты после выполнения работы

Эксперименты уже выполнены, опасные профили сняты. Не нужно одновременно держать кластер в preemption и MemoryPressure: эти состояния кратковременны и взаимоисключают обычный рабочий профиль.

Открой `REVIEW.html` в браузере. Там собраны **сохранённые реальные наблюдения с датами**, клиентские графики k6 и графики из Prometheus. Это архив, а не живой вывод kubectl. Если открытие локального HTML неудобно:

```bash
cd lecture-4-scheduling-resources
python3 -m http.server 8764 --bind 127.0.0.1
# В браузере: http://127.0.0.1:8764/REVIEW.html
```

Нужны следующие снимки (сохрани в `screenshots/`):

| Файл | Что показать |
|---|---|
| `01-spread.png` | Раздел 1: две API-реплики, разные NODE. Можно вместо архива снять живой `kubectl -n shop get pods -o wide`. |
| `02-krr.png` | Раздел 2: финальная таблица krr, параметры simple-limit, ссылка на исходный JSON. |
| `03-qos.png` | Раздел 3: Guaranteed у API/PostgreSQL, Burstable у batch, разные PRIORITY и PDB. |
| `04-pending.png` | Раздел 4: batch Pending, FailedScheduling / Insufficient cpu. |
| `05-preemption.png` | Раздел 5: события Preempted by pod для batch на обеих нодах и четыре Ready API. |
| `06-eviction.png` | Раздел 6: reason=Evicted, сообщение low on resource: memory, request=96Mi и использование ниже limit=1Gi; критические Pod остаются. |
| `07-oom.png` | Раздел 7: OOMKilled и restartCount у контейнера с limit=128Mi. Это контрольный опыт для сравнения. |
| `08-sla-cpu.png` | График k6 CPU/preemption: клиентский p95 и ошибки, линии SLA, отметки этапов. |
| `09-sla-memory.png` | График k6 MemoryPressure: p95 и ошибки, отметки eviction-опыта и восстановления. |
| `10-dashboard.png` | Сводный дашборд реальных рядов Prometheus либо живой Grafana с историческим диапазоном экспериментов. |
| `11-alert-firing.png` | Последний раздел: реальный ответ API Prometheus с ShopBatchUnschedulable state=firing. |

Терминальная альтернатива архивному HTML: `cat evidence/06-preemption.txt`, `cat evidence/07-eviction.txt`, `cat evidence/09-ShopBatchUnschedulable-firing.json`. Полные исходные снимки лежат рядом; HTML сокращает только нерелевантные старые события для удобства чтения.

Живой Grafana:

```bash
kubectl -n monitoring port-forward svc/grafana 3000:80
# http://127.0.0.1:3000/d/shop-resources
```

Вход прежний, от Лабы 2. Выбери абсолютный диапазон из `evidence/phases.json` (время там Unix UTC). В Grafana timezone=browser, поэтому на этом стенде будет UTC+3. PNG графики подписаны UTC. Если прошло больше retention Prometheus (6 часов), используй сохранённый дашборд в REVIEW.html и `evidence/09-dashboard.png`.

Скриншоты создаются тобой; их отсутствие сейчас не подменяется сгенерированными изображениями интерфейса. После съёмки можно вставить реальные PNG в REPORT.md. Диаграммы в evidence — экспорт измерений, а не скриншоты.
