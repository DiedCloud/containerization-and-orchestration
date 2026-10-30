# Часть 1 — ограждения на кластер

## Почему Kyverno

Выбрал Kyverno: для пяти проверок достаточно обычных Kubernetes-манифестов,
не нужно осваивать Rego. Движок подключается к admission API-сервера и
проверяет объект до сохранения в etcd. `failureAction: Enforce` означает
реальный отказ, тогда как `Audit` только сообщает о нарушении.

Использую официальный Helm-чарт `kyverno/kyverno` **3.9.2**, приложение
**v1.19.2**. Его исходники в репозиторий не копирую: хранятся только
[наши overrides](../platform/kyverno-values.yaml) и команда с `--version`.
Доступные параметры можно посмотреть через
`helm show values kyverno/kyverno --version 3.9.2`.

Chart состоит из `Chart.yaml`, `templates/` и `values.yaml`. Helm подставляет
values в шаблоны и отправляет обычные манифесты в Kubernetes; результат
рендеринга показывает `helm template`. Установленная копия — release,
каждое обновление создаёт ревизию в Secret её namespace. История нужна для
`helm rollback`. Приоритет values: defaults чарта, затем файлы `-f` по
порядку, затем `--set`.

На одной ноде достаточно одной реплики admission controller. Reports
controller оставлен для отчётов; background controller для generate/mutate
и cleanup controller отключены, поскольку такие функции здесь не нужны.
Это не отказоустойчивая установка. У webhook установлен `failurePolicy: Fail`:
если проверка недоступна, подходящий запрос не должен проходить незаметно.

## Пять правил

Все правила находятся в одном [ClusterPolicy](guardrails.yaml).

| Правило | Что проверяет | Зачем |
| --- | --- | --- |
| `require-resource-limits` | Положительные `limits.cpu` и `limits.memory` у каждого обычного и init-контейнера | CPU ограничивается throttling, превышение памяти приводит к OOM внутри лимита; контейнер не получает неограниченный бюджет ресурсов ноды. Requests зададим в чарте отдельно для планировщика. |
| `require-app-label` | Непустую метку `app` у Pod и Pod template | Можно однозначно выбирать приложение в Service, командах и мониторинге. Наличие метки само по себе не гарантирует правильность селекторов. |
| `trusted-image-sources` | Источник `docker.io/library/*` или `ghcr.io/cloudnative-pg/*` | Ограничивает набор источников: наш локально собранный `shop`, официальные Docker Library и PostgreSQL оператора. Проверяет также init/ephemeral containers. |
| `disallow-privileged` | `privileged` отсутствует или равен `false` | Контейнеру нельзя включить полный privileged-режим и получить широкие права над хостом. Проверяет также init/ephemeral containers. |
| `disallow-host-namespaces` | `hostNetwork`, `hostPID`, `hostIPC` отсутствуют или равны `false` | Приложение не должно разделять сетевое пространство, процессы и IPC с нодой. |

Registry-проверка сначала вызывает `image_normalize`. У Kyverno v1.19.2
сокращённый образ `shop:1.0.0` становится `docker.io/shop:1.0.0`, без сегмента
`library/`. Поэтому разрешены и эта запись Docker Library с одним компонентом,
и явный путь `docker.io/library/shop:1.0.0`. Произвольные namespace вроде
`docker.io/untrusted/shop:1.0.0` и похожие имена `library.evil` запрещены.
Это важно и для существующего `api:lab2-source` из Лабы 2. Разрешение источника
не подтверждает автора, подпись или безопасность конкретного образа. В нашей
лабе `shop` загружается в kind локально, публикация в Docker Hub не нужна.
В `ghcr.io` разрешён только путь `cloudnative-pg`, а не весь реестр.

Ephemeral containers не поддерживают собственные `resources`, поэтому
проверка limits применяется только к обычным и init-контейнерам.

## Область действия

`ClusterPolicy` действует кластерно: в `shop`, `default` и любых будущих
прикладных namespace. Opt-in метка namespace не нужна.

Исключения явно перечислены в каждом правиле: `kube-system`, `kube-public`,
`kube-node-lease`, `local-path-storage`, `kyverno`, `monitoring`, `cnpg-system`.
Сетевые/системные компоненты могут требовать hostNetwork и другие источники
образов; мониторинг из Лабы 2 оставляю с его существующими настройками.
Исключение `cnpg-system` относится только к контроллеру будущего оператора:
созданные им Pod базы в `shop` будут проверяться.
Это осознанные инфраструктурные исключения, а не утверждение, что политики
проверяют абсолютно каждый системный Pod.

Kyverno автоматически переносит правила для Pod на Pod templates
Deployment/StatefulSet/DaemonSet/Job/CronJob/ReplicaSet/ReplicationController.
Поэтому неправильный Deployment можно отклонить ещё до создания ReplicaSet и
Pod. В манифесте это включено аннотацией `autogen-controllers`.
Проверки выполняются при CREATE и UPDATE; удаление правила не запрещают.
`background: true` включает проверку сохранённых объектов в отчётах, но
не удаляет и не перезапускает уже работающие Pod.

## Установка до чарта shop

Из корня репозитория:

```bash
bash lecture-3-kubernetes-control-plane/platform/install-kyverno.sh
kubectl --context kind-lab2 get pods -n kyverno
kubectl --context kind-lab2 get clusterpolicy platform-guardrails
```

Все пять действий `Enforce` можно вывести явно (вместо устаревшей общей
колонки действия политики):

```bash
kubectl --context kind-lab2 get clusterpolicy platform-guardrails -o 'custom-columns=NAME:.metadata.name,ACTIONS:.spec.rules[*].validate.failureAction,READY:.status.conditions[?(@.type=="Ready")].status'
```

Скрипт закрепляет версию, предварительно скачивает официальные образы на
хост, загружает их в `kind` и устанавливает чарт. Затем создаёт namespace
`shop`, применяет политику и ждёт `Ready`. Для другого kind-кластера можно
задать `KIND_CLUSTER` и `KUBE_CONTEXT`.

### Проблема при установке

При первой установке нода kind не смогла разрешить `reg.kyverno.io` через
свой DNS `172.20.0.1:53`: `server misbehaving`, затем `ErrImagePull` и
`ImagePullBackOff`. Helm завершил ожидание по таймауту. С хоста те же образы
успешно скачались. Поэтому использую `docker pull` + `kind load docker-image`
с исходными именами; сторонний чарт не меняю.

При проверке обнаружился и ложный отказ короткого образа: изначально правило
ожидало обязательный сегмент `/library/`. Через официальный `kyverno-cli`
проверил результат `jp query "image_normalize('shop:1.0.0')"` и исправил
регулярное выражение. Добавил положительную проверку короткого имени и
отрицательные проверки постороннего namespace и похожего префикса.

## Проверка admission

Пять файлов в `examples/01-*.yaml` — `05-*.yaml` нарушают по одному правилу.
`examples/valid.yaml` удовлетворяет всем пяти.

```bash
python3 lecture-3-kubernetes-control-plane/policies/verify.py
```

Первые пять запросов действительно пытаются создать Pod и должны быть
отклонены webhook. Проверяется не просто ненулевой код возврата, а имя нашей
политики и конкретного правила; отказ по другим правилам считается ошибкой
теста. Корректный Pod и дополнительные случаи проверяются через
`--dry-run=server`, поэтому тестовые Pod не остаются в кластере.

Дополнительные проверки: разрешённый короткий образ, CloudNativePG image,
запрет чужого образа в `default`, посторонний Docker Hub namespace и похожий
префикс, hostPID/hostIPC, три нарушения в
initContainer и два Deployment, чтобы проверить autogen.

Проверка выполнена на кластере: **5 отдельных отказов + 13 дополнительных
проверок, PASS**. Вывод сохранён в
[evidence/01-policies.txt](../evidence/01-policies.txt). Корректный Pod и
Deployment прошли admission, неправильный Deployment был отклонён правилом
`autogen-require-resource-limits`. Существующий Deployment API Лабы 2 тоже
прошёл server dry-run обновления.

**Скриншоты для отчёта:**

1. `kubectl get pods -n kyverno` и `kubectl get clusterpolicy` — готовый движок
   и политика в `Enforce`.
2. Вывод `verify.py`: пять отдельных отказов и итоговый `PASS`. Если вывод
   не помещается, сделать несколько снимков.

## Источники

- [Установка Kyverno](https://kyverno.io/docs/installation/installation/).
- [Validate и foreach](https://kyverno.io/docs/policy-types/cluster-policy/validate/).
- [Настройки ClusterPolicy](https://kyverno.io/docs/policy-types/cluster-policy/policy-settings/).
- [Релиз v1.19.2](https://github.com/kyverno/kyverno/releases/tag/v1.19.2).
