# Лабораторная 5 — Zero-trust сеть с доказательством

## Стенд и выбор CNI

Использовал существующий двухнодовый `kind-lab2` из Лаб 2–4. Prometheus, Grafana, Alertmanager и PostgreSQL на PVC сохранил, новый стек мониторинга не поднимал. Chart `shop` продолжает собственный chart предыдущих работ; убрал batch и опыты с ресурсами, оставил API, worker и CNPG PostgreSQL. Для сетевых проверок добавил client и stranger с тем же образом приложения.

Выбрал Cilium 1.20.4: он применяет NetworkPolicy через eBPF, а Hubble показывает источники, адресатов и причины отбрасывания пакетов. Для скрытой поломки это полезнее одного таймаута клиента. Calico тоже подходит для изоляции, но здесь хотелось проверить диагностику по Hubble. `kindnet` заменил: он принимает объекты NetworkPolicy через Kubernetes API, но сам их не исполняет.

Сохранил kube-proxy, настроил Cilium с `ipam.mode=kubernetes`, native routing и `autoDirectNodeRoutes`. Он использует прежние PodCIDR `10.244.0.0/16`; ноды напрямую маршрутизируют пакеты между своими подсетями. После установки пересоздал старые Pod, чтобы они получили Cilium endpoints. PVC базы не удалял.

Cilium установлен из внешнего Helm repo с закреплённой версией, в репозитории лежат только [overrides](infrastructure/cilium-values.yaml) и [скрипт установки](infrastructure/install-cni.sh). Копировать сторонний chart не нужно; доступные параметры показывает `helm show values cilium/cilium --version 1.20.4`.

Helm chart — пакет из `Chart.yaml`, `values.yaml` и шаблонов `templates/`. Helm объединяет defaults, файлы `-f` и `--set` (последний слой побеждает), рендерит обычные Kubernetes-объекты и применяет их. Результат виден через `helm template`. Установленная копия — release, каждая ревизия хранится в Secret его namespace: на этой истории основан rollback.

При запуске обе ноды были остановлены: сначала запустил их Docker-контейнеры. Затем Cilium получил ImagePullBackOff: из нод quay.io отвечал таймаутом. Образы скачал на хост и загрузил через `kind load docker-image`, сохранив upstream теги и digest.

Дополнительно Cilium 1.18.3 падал до готовности на ядре хоста `7.2.11-arch1-1`: `failed to probe helper ... FnSetRetval ... R1 is not a scalar`. Нашёл [upstream issue #48016](https://github.com/cilium/cilium/issues/48016): старый probe не учитывает новую проверку аргумента `bpf_set_retval`. Перешёл на **Cilium 1.20.4**, где ошибка исправлена. Это окончательная закреплённая версия стенда; Helm overrides отключают `useDigest`, чтобы kind использовал загруженные локальные образы по тегу.

На Kubernetes 1.37 после неудачного pull одного импорта оказалось недостаточно: kubelet повторно проверял доступ к registry, а с `Never` показывал ErrImageNeverPull при наличии образа в `crictl images`. Настроил `NeverVerifyAllowlistedImages` для репозиториев уже загруженных образов стенда, затем перезапустил kubelet. Механизм описан в [документации Kubernetes](https://kubernetes.io/docs/concepts/containers/images/#ensure-image-pull-credential-verification). Настройка и загрузка включены в `infrastructure/preload-images.py`.

## Сеть Pod

При создании Pod runtime создаёт network namespace, а Cilium через CNI выдаёт IP из PodCIDR ноды, настраивает `eth0`, маршруты и парный veth. Один конец находится в namespace Pod, другой (`lxc…`) — в namespace ноды. На veth/интерфейсах Cilium ставит eBPF-программы: они маршрутизируют трафик и применяют политики по идентичности endpoint.

В [измерении сети](evidence/network.txt) API `shop-api-846d9db8cf-fgdhq` получил `10.244.0.21`, `eth0 ifindex=54`, `iflink=55`. На control-plane интерфейс `lxce3bd250598fc` имеет ifindex=55 и peer `@if54`: это два конца одной пары. Запрос на `10.244.1.162:8000/health` вернул `ok` с другой ноды. Межнодовый маршрут идёт через `172.20.0.3 dev eth0`; NAT между IP Pod для этого не нужен.

![IP и eth0 внутри Pod, парный veth на ноде, межнодовый запрос и режим kube-proxy](screenshots/01-pod-network.png)

На снимке есть старый Completed API предыдущего rollout: это уже завершённая реплика, в проверке участвовали Running Pod. Скриншоты команд в отчёте — отображение сохранённого фактического stdout; веб-интерфейсы сняты непосредственно в браузере.
