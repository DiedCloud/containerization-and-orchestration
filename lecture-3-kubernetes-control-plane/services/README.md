# Сервисы shop

Один образ содержит API и worker; команда uvicorn выбирает api:app или
worker:app. Оба слушают порт 8000 и предоставляют /health и /metrics.
Контейнер работает от UID 10001 без root.

API принимает `POST /order` с JSON `{"item":"book","quantity":2}`,
сохраняет заказ в PostgreSQL и возвращает список через `GET /orders`.
Worker заполняет processed_at и processed_by. Выбор строки с
`FOR UPDATE SKIP LOCKED` и обновление выполняются в одной транзакции:
несколько worker не берут один заказ одновременно. SQL-параметры
передаются отдельно от текста запроса.

При старте приложения создают схему, сериализуя DDL через advisory lock.
Подключение DATABASE_URL передаётся из Secret CloudNativePG. При ошибке БД
API возвращает 503, worker пишет ошибку и повторяет попытку.

`HEALTH_FAIL=true` включает 503 на /health для проверки rollout. Обычный
health API не зависит от БД; у worker он проверяет работающий цикл обработки.
Дополнительный /ready worker и heartbeat-метрика проверяют свежий успешный
опрос БД, поэтому отказ PostgreSQL не вызывает лишние liveness-рестарты.

[Сборка и установка в Kubernetes](../shop/README.md),
[результаты проверки заказов](../REPORT.md).
