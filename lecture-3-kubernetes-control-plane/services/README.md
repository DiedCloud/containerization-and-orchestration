# Часть 0: сервисы shop

Один образ содержит два приложения: `api:app` и `worker:app`. Команда запуска
выбирает роль. Оба слушают порт 8000 и предоставляют `/health` и `/metrics`.
Контейнер работает от UID 10001 без root.

API принимает `POST /order` с JSON `{"item":"book","quantity":2}` и отдаёт
заказы через `GET /orders`. Поля `processed_at` и `processed_by` показывают,
что заказ обработан. Параметры SQL передаются отдельно от текста запроса.

Worker выбирает заказ с `FOR UPDATE SKIP LOCKED` и обновляет его в той же
транзакции. Другие worker пропускают заблокированную строку. Если транзакция
оборвётся, PostgreSQL откатит изменение и освободит блокировку. Это подходит
для нашей обработки внутри БД; произвольные внешние действия потребовали бы
отдельной защиты от повторного выполнения.

Схему при старте создают сами приложения. Advisory lock сериализует DDL от
нескольких реплик. При недоступности БД старт повторяется до 60 попыток.
В реальном приложении изменения схемы лучше выполнять отдельными миграциями.

`HEALTH_FAIL=true` заставляет `/health` отвечать 503 для эксперимента с rollout.
API после старта проверяет на `/health` только сам процесс, чтобы проблемы БД
не вызывали перезапуски всех API. Worker дополнительно проверяет, что недавно
успешно обращался к БД. При ошибках запросы API к заказам возвращают 503;
worker пишет ошибку в лог и повторяет попытку.

## Проверка без Kubernetes

Из корня репозитория:

```bash
docker build -t docker.io/library/shop:1.0.0 lecture-3-kubernetes-control-plane/services
docker compose -p lab3-smoke -f lecture-3-kubernetes-control-plane/services/compose.yaml up -d --scale worker=2
docker compose -p lab3-smoke -f lecture-3-kubernetes-control-plane/services/compose.yaml cp lecture-3-kubernetes-control-plane/services/smoke.py api:/tmp/smoke.py
docker compose -p lab3-smoke -f lecture-3-kubernetes-control-plane/services/compose.yaml exec -T api python /tmp/smoke.py
curl -s http://localhost:18080/health
curl -s http://localhost:18080/orders | python3 -m json.tool
```

Smoke-тест отправляет 50 заказов параллельно, проверяет уникальность ID,
сохранение и обработку всех заказов, метрики, валидацию тела и сломанный health.
Повторный запуск добавит ещё 50 заказов.

**Скриншот:** вывод smoke-теста и `/orders`, где заполнены `processed_at` и
`processed_by`. Сохранить в `../screenshots/00-services.png`.

Остановка временного окружения (тестовые данные больше не нужны):

```bash
docker compose -p lab3-smoke -f lecture-3-kubernetes-control-plane/services/compose.yaml down -v
```

Compose нужен только для проверки кода. В Kubernetes PostgreSQL будет создан
оператором, а адрес подключения приложения получат из Secret.

Документация механизма блокировок:
[PostgreSQL SELECT — locking clause](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE).
