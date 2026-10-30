# Рекомендации krr v1.31.1

История: 1 час (включая период нагрузки 10 POST /order в секунду). CPU p99, память max +15%, минимальная память krr 100Mi, шаг 1 минута, минимум 20 точек.

| Сервис | CPU request | Память request = limit |
|---|---|---|
| api | 61m | 100Mi |
| worker | 46m | 100Mi |
| postgres | 156m | 100Mi |

CPU limit исходно unset: в финальном Guaranteed-профиле он приравнен к CPU request. KRR предупреждает NotEnoughHistoryAvailable: лабораторная история короче рекомендуемой длительной выборки. Batch не является целью rightsizing, его значения меняются для экспериментов.
