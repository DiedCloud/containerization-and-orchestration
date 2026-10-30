# Ход лабораторной 4

Исходное состояние: kind-lab2, одна нода; shop revision 10; мониторинг Лабы 2 и политики Лабы 3 работают. Пользовательские незакоммиченные изменения не включать в коммиты.

- [x] 0. Batch: регулируемое потребление памяти и CPU, Dockerfile.
- [x] 1. Выбор разнесения.
- [x] 2. Две ноды, batch через Helm, guardrails.
- [x] 3. Нагрузка и реальные рекомендации krr.
- [x] 4. Разнесение API.
- [x] 5. Guaranteed, приоритеты, PDB.
- [x] 6. Pending и preemption.
- [x] 7. MemoryPressure и eviction.
- [x] 8. SLA во время экспериментов, графики.
- [x] 9. Дашборд и три алерта, firing.
- [x] Отчёт и воспроизводимый просмотр доказательств для скриншотов.

Не подменять реальные результаты ожидаемыми. В конце вернуть рабочий профиль нагрузки. Временные секреты/Helm values только в artifacts.local.

## Продолжение 31 октября

- Этапы 0–4 закоммичены. Shop chart 0.2.0 — отдельная версия в lab4.
- Работают две ноды существующего kind-lab2. Worker добавлен через kubeadm, образы предзагружены. Исходные user dirty files не тронуты.
- Официальный krr v1.31.1 без CNPG discovery; сделан read-only адаптер, алгоритм untouched. Source /tmp/lab4-krr-source, инструменты docker lab4-krr-tools (Python3.12 + upstreamrequirements; DNS pip в контейнере неработает, скачали wheels на хосте).
- Бинарный k6 /tmp/lab4-bin/k6-v2.3.0-linux-amd64/k6. Локальный Prometheus http://127.0.0.1:19091 (port-forward 27833). Второй forward19090 лишний.
- Initial krr simple p99: API61m/100Mi, worker46m/100Mi, PG156m/100Mi. Initialbaseline2621orders p9529ms, intentionally stopped at4m22, INTERRUPTreported.
- Guaranteed initial numbers вызвали тяжёлый CPU throttling, ошибки CNPG probes/lease, SLAfail (05-too-small*). GOMAXPROCS1+probes не решили. Recoveryrollback13 и принудительная остановка уже удаляемого PGконтейнера через crictl (gracefultimeoutCNPG1800sec); PVCсохранён. Добавлены chart stopDelay30/smartShutdownTimeout10.
- Сейчас profiling с запасом API500m/256Mi, PG1cpu/256Mi; затем k6 RATE30 DURATION2m. Нужно дождаться session71799. Ранее30RPS при API61mнепоказателен, сохранён 05-profiling* отдельно.
- Следующий шаг: krr native simple_limit CPUrequest100/limit100, memory_buffer_percentage100, history1h step1min points20; сохранить03-krr-final.json, применить точно его числаAPI/worker/PG в chart. Проверить15s/60shealthyload10RPS, только потом commitstage5. Старыеbadexperimentsсохранитьотчёт.
- Shop Helm4.3: --wait=legacy плюс kubectlwaitCNPG корректнее. Обычный watcherотмечаетнеReadyClusterиtimeout.
- Мониторинг уже синхронизирован (скриптЛабы3), Prometheusrev10, GrafanaexistingnewdashboardUIDshop-resources. Правила ровно3: SLOBreach,BatchUnschedulable,NodeMemoryPressure, upstreamLab2rulespreserved. НуженfiringпослеPendingbatch.
- Готовыscripts/exps stage6/7 + dashboard + exports/reviewbuilder, но не выполнены. Stage6 capacity script оставит2batchslots500m/нода и headroom<APIrequest. Fill8pods =>Pending; APIscale4=>preempts batch. Startk6 06-cpu4m beforefill, capturealertfiring, snapshots06-pending/preemption, markphases, restorecapacity/defaults, commit6.
- Stage7 startk6 07-memory4m, runmemory-experiment: thresholdworkeravailable-384Mi, batch2x768Mi limit1Gi gradualalloc. CapturememoryPressure/Evicted, criticalUIDs/restarssame. Finally restores100Mi/defaults. Needcheckmemorypressuretoo(notonlyeviction).
- SeparateOOMcontrol128Milimit256Miallocationafterthresholdrestore, capturelastStateOOMKilled in07-oom-control.txt thenrestoredefaults.
- ExportPrometheus12panelranges, build-review.py via docker toolsplotlib saves3PNG+REVIEW.html with archivedactualevidence. NeedfinalREPORT.md Russianstudentlike priorreports and SCREENSHOTS.md useronlyscreenshotsend. Stage8/9commits, finalvalidationallchartKRRmatch/liveqoshealth/no pendingcritical, preserveuserdirtyfiles.


## Финал

Все части 0–9 выполнены на живом стенде. Финальные числа krr: API 486m/131Mi, worker 217m/100Mi, PostgreSQL 870m/212Mi. CPU: 2400 заказов, p95 27,87 мс; память: 2401 заказ, p95 29,66 мс. Ошибок и пропусков нет. Critical Pod UID и restarts не изменились при давлении памяти. Release 28 deployed, шесть активных Pod Ready; исторические Evicted сохранены для съёмки. Четыре цели UP, три правила здоровы и inactive. Финальная уборка отложена до отдельной просьбы пользователя.
