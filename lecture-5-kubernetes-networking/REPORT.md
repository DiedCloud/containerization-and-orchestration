# Лабораторная 5 — Zero-trust сеть с доказательством

## Стенд и выбор CNI

Использовал существующий двухнодовый `kind-lab2` из Лаб 2–4. Prometheus, Grafana, Alertmanager и PostgreSQL на PVC сохранил, новый стек мониторинга не поднимал. Chart `shop` продолжает собственный chart предыдущих работ; убрал batch и опыты с ресурсами, оставил API, worker и CNPG PostgreSQL. Для сетевых проверок добавил client и stranger с тем же образом приложения.

Выбрал Cilium 1.18.3: он применяет NetworkPolicy через eBPF, а Hubble показывает источники, адресатов и причины отбрасывания пакетов. Для скрытой поломки это полезнее одного таймаута клиента. Calico тоже подходит для изоляции, но здесь хотелось проверить диагностику по Hubble. `kindnet` заменил: он принимает объекты NetworkPolicy через Kubernetes API, но сам их не исполняет.

Сохранил kube-proxy, настроил Cilium с `ipam.mode=kubernetes`, native routing и `autoDirectNodeRoutes`. Он использует прежние PodCIDR `10.244.0.0/16`; ноды напрямую маршрутизируют пакеты между своими подсетями. После установки пересоздал старые Pod, чтобы они получили Cilium endpoints. PVC базы не удалял.

Cilium установлен из внешнего Helm repo с закреплённой версией, в репозитории лежат только [overrides](infrastructure/cilium-values.yaml) и [скрипт установки](infrastructure/install-cni.sh). Копировать сторонний chart не нужно; доступные параметры показывает `helm show values cilium/cilium --version 1.18.3`.

Helm chart — пакет из `Chart.yaml`, `values.yaml` и шаблонов `templates/`. Helm объединяет defaults, файлы `-f` и `--set` (последний слой побеждает), рендерит обычные Kubernetes-объекты и применяет их. Результат виден через `helm template`. Установленная копия — release, каждая ревизия хранится в Secret его namespace: на этой истории основан rollback.

При запуске обе ноды были остановлены: сначала запустил их Docker-контейнеры. Затем Cilium получил ImagePullBackOff: из нод quay.io отвечал таймаутом. Образы скачал на хост и загрузил через `kind load docker-image`, сохранив upstream теги и digest.
