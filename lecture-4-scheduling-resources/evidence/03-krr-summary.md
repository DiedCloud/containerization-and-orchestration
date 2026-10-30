# Финальные рекомендации krr v1.31.1

Upstream simple_limit: CPU request p100 = limit p100, memory max+100%; history 1h, step 1min, points_required=20. Профилирование включает 30 POST /order в секунду и перезапуски компонентов. Абсолютные числа взяты из 03-krr-final.json.

| Сервис | CPU request | RAM request = рекомендованный limit |
|---|---|---|
| api | 486m | 131Mi |
| worker | 217m | 100Mi |
| postgres | 870m | 212Mi |

API/postgres: limits=requests для Guaranteed. Worker остаётся Burstable с limits 250m/128Mi. Первый simple p99 дал 61m/100Mi API и 156m/100Mi PostgreSQL: при превращении request в limit возникли throttling, сбой CNPG probes/lease и нарушение SLA. Поэтому исходная оценка не выдана за успешный финальный результат. Оба JSON сохранены. История лабораторная, предупреждение KRR NotEnoughHistoryAvailable сохранено; для production нужна длительная репрезентативная выборка.
