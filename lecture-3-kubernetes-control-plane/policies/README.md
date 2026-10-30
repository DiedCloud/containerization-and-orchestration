# Политики кластера

Выбрал Kyverno: для этих правил достаточно Kubernetes YAML, отдельный язык
Rego не нужен. Admission webhook проверяет объект до сохранения в etcd.
`Enforce` отклоняет нарушение, `Audit` только сообщает о нём.

Официальный чарт `kyverno/kyverno` 3.9.2 (v1.19.2) устанавливается скриптом
`platform/install-kyverno.sh` до чарта shop. Исходники upstream не копируются.
Для одной ноды оставлены admission и reports controller по одной реплике;
background и cleanup controller отключены. Это не отказоустойчивая установка.
`failurePolicy: Fail` запрещает пропускать запрос при недоступной проверке.

## Пять правил

Все правила находятся в [guardrails.yaml](guardrails.yaml).

| Правило | Проверка и причина |
| --- | --- |
| `require-resource-limits` | Положительные CPU/memory limits у обычных и init-контейнеров ограничивают потребление ресурсов ноды. Requests в чарте задаются отдельно для планировщика. |
| `require-app-label` | Непустая метка app нужна для выбора приложения. Наличие метки само по себе не гарантирует правильность селекторов. |
| `trusted-image-sources` | Только Docker Library и ghcr.io/cloudnative-pg; ограничивает источники, но не проверяет подписи образов. Проверяются также init и ephemeral containers. |
| `disallow-privileged` | Запрет privileged=true не позволяет включить полный privileged-режим. Проверяются также init и ephemeral containers. |
| `disallow-host-namespaces` | Запрет hostNetwork, hostPID, hostIPC отделяет сеть, процессы и IPC приложения от ноды. |

Ephemeral containers не поддерживают собственные resources, поэтому limits
проверяются только у обычных и init-контейнеров. У Kyverno v1.19.2
`image_normalize('shop:1.0.0')` даёт `docker.io/shop:1.0.0`, без `/library/`.
Правило допускает обе записи Docker Library, но запрещает произвольные
Docker Hub namespace и похожий префикс library.evil. Образы shop загружаются
в kind локально; публикация в Docker Hub не нужна.

## Область действия

ClusterPolicy распространяется на shop, default и новые прикладные namespace.
Явно исключены kube-system, kube-public, kube-node-lease, local-path-storage,
kyverno, monitoring и cnpg-system: инфраструктуре нужны другие образы и
иногда hostNetwork. Pod PostgreSQL создаются в shop и проходят проверки.

Autogen проверяет Pod templates Deployment, StatefulSet, DaemonSet, Job,
CronJob, ReplicaSet и ReplicationController. Правила действуют на CREATE и
UPDATE. Background-проверка сообщает о существующих нарушениях, но не
удаляет и не перезапускает работающие Pod.

## Проверка отказов

Из корня репозитория:

```bash
bash lecture-3-kubernetes-control-plane/platform/install-kyverno.sh
python3 lecture-3-kubernetes-control-plane/policies/verify.py
```

Пять файлов `examples/01-*` — `05-*` нарушают по одному правилу;
`examples/valid.yaml` удовлетворяет всем пяти. Скрипт проверяет реальные
отказы создания с именем нужного правила, затем server dry-run для корректных
манифестов, init-контейнеров и Deployment autogen. Результат: пять отказов
и 13 дополнительных проверок, тестовые Pod не остались в кластере.
[Скриншоты и проблемы установки](../REPORT.md).
