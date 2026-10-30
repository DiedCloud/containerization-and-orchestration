# Инструменты измерений

Использованы k6 v2.3.0 (официальный linux-amd64 release Grafana) и krr v1.31.1.
KRR из официального бинарника использовался для первичной проверки Deployment.
Для CloudNativePG использован исходный код того же тега и `scripts/krr-cnpg.py`.
Адаптер расширяет только discovery: в Kubernetes он ничего не создаёт и не изменяет.

Исходный checkout `/tmp/lab4-krr-source` и контейнер `lab4-krr-tools` — временное окружение инструментов. Python 3.12, зависимости из upstream requirements.txt. Установка pip внутри контейнера не могла разрешить DNS: колёса скачаны на хосте через pip download для Python 3.12, затем установлены offline. Алгоритм KRR не изменялся.

Повторный запуск на подготовленном окружении:

```bash
docker exec lab4-krr-tools python /repo/lecture-4-scheduling-resources/scripts/krr-cnpg.py simple \
  -n shop -p http://127.0.0.1:19091 --history_duration 1 --timeframe_duration 1 \
  --points_required 20 --cpu_percentile 99 -f json \
  --fileoutput /repo/lecture-4-scheduling-resources/evidence/03-krr.json
```

Prometheus доступен через `kubectl -n monitoring port-forward svc/prometheus-server 19091:80`.
KRR по умолчанию не рекомендует CPU limit; guardrails требуют его, а Guaranteed требует равенства requests/limits. Поэтому финальный CPU limit критических компонентов равен CPU request из отчёта. Память берётся напрямую из рекомендации, одинаковой для request и limit.

100Mi — нижняя граница стандартной стратегии KRR, а не измеренное потребление ровно 100Mi. CPU p99 выбран для коротких всплесков при создании заказов. Часовая история — лабораторная выборка, предупреждение KRR об истории сохранено в JSON; для production нужна длительная репрезентативная нагрузка.

Первый профиль `simple` оказался слишком тесным для instance manager CNPG при принудительном равенстве limit=request. Проверка `05-steady-*` показала нарушение SLA; это подготовительный неуспешный опыт, не скрытая часть успешного интервала. Таймаутов probes и GOMAXPROCS=1 оказалось недостаточно. Повторное профилирование выполнялось с временным запасом PostgreSQL (1 CPU/256Mi) и 30 заказами/с, чтобы увидеть потребление без прежнего жёсткого ограничения. SLA итогового опыта заявлен для 10 заказов/с.

Финальная стратегия: upstream `simple_limit`, CPU request p100 и limit p100, memory max+100%. Так Guaranteed использует явно рекомендованный krr лимит, а память включает запас для служебного Go instance manager и процессов PostgreSQL. Проценты — параметры стратегии, абсолютные CPU/memory взяты из её отчёта. Старый отчёт сохранён отдельно, итоговый — `03-krr-final.json`.

Финальная команда (Typer преобразует имя стратегии в simple-limit):

```bash
docker exec lab4-krr-tools python /repo/lecture-4-scheduling-resources/scripts/krr-cnpg.py simple-limit \
  -n shop -p http://127.0.0.1:19091 --history_duration 1 --timeframe_duration 1 \
  --points_required 20 --cpu_request 100 --cpu_limit 100 --memory_buffer_percentage 100 \
  -f json --fileoutput /repo/lecture-4-scheduling-resources/evidence/03-krr-final.json
```

Финальные CPU/memory requests API, worker и PostgreSQL автоматически сверены с JSON KRR через scripts/verify.py. Для API/PostgreSQL requests и limits совпадают; worker сохраняет 250m/128Mi limits.
