# Docker launcher: команды, ресурсы и изоляция

Штатный пользовательский маршрут — [руководство пользователя](../user/README.md).
Ниже справочник host launcher `python3 scripts/docker_scanner.py`; он требует
только stdlib Python 3.11+ и локальный Docker/Compose. Установленный Python CLI
внутри image описан в [конфигурации](configuration.md).

## Команды и отличия entry points

```text
python3 scripts/docker_scanner.py verify --deployment-lock FILE
python3 scripts/docker_scanner.py snapshot --deployment-lock FILE --repo PATH --commit REV --output DIR [OPTIONS]
python3 scripts/docker_scanner.py diff --deployment-lock FILE --repo PATH --from REV --to REV --output DIR [OPTIONS]
python3 scripts/docker_scanner.py export --deployment-lock FILE --directory NEW_DIR
python3 scripts/docker_scanner.py import --directory PACKAGE_DIR
```

Без явного `--deployment-lock` default — `locks/scanner-cpu-linux-arm64.deployment.json`
относительно корня установки launcher. Это измеренный исторический образ, не
универсальный выбор для fresh build. `import` выбирает deployment внутри пакета.
Все subcommands поддерживают `--help`; отдельного `--version` у host launcher нет.

`snapshot/diff` принимают параметры анализа/scope/presentation из
[конфигурации](configuration.md), `--config`, а diff — baseline/strict-флаг.
Пути/refs задаются явными argv. `--engine-dir` и `--analyzer-url` доступны только
у установленного Python CLI: Docker engine находится внутри image, URL всегда
`http://analyzer:5001`, даже если config задаёт другой адрес.

В неопубликованных AMD64/ARM64 кандидатах версии certifi сохранены по
[решению владельца](../../verification/linux-amd64/certifi-advisory.md).
Принятая конфигурация ограничена штатным offline Docker-маршрутом с внутренним
HTTP. Произвольный HTTPS endpoint установленного Python CLI требует отдельной
оценки CA policy и зависимостей до использования; программного запрета HTTPS
этим решением не добавлено.

## Бюджеты контейнеров

| Аргумент launcher | Default | Ограничение |
| --- | --- | --- |
| `--analyzer-cpus` | `2.0` | Положительное конечное число |
| `--scanner-cpus` | `1.0` | Положительное конечное число |
| `--analyzer-memory` | `3g` | `2g`, `3g`, `4g`, `6g`, `8g` |
| `--scanner-memory` | `1g` | `512m`, `1g`, `2g`, `4g`, `8g` |
| `--run-timeout-seconds` | `3600.0` | Положительное конечное число |
| `--stop-grace-seconds` | `30.0` | Положительное конечное число |

Analyzer получает tmpfs 1 GiB, scanner — 512 MiB. Tmpfs входит в memory budget,
дополнительный swap не выделяется. Defaults проверены на небольшом синтетическом
code-v1 и цепочках состояний в [результатах](../../verification/README.md).
Это не гарантированные минимальные требования или ёмкость для любого клона.

`ready-timeout` ограничивает ожидание закреплённой модели, `analyze-timeout` —
обработку одного полного файла. Автоматических повторов анализа нет.
`run-timeout` начинается после preflight образов/путей перед подготовкой Compose;
Docker-команды имеют собственные таймауты. Это не точный общий wall deadline.
Отмена допускает join уже начавшейся CPU-работы и сохранение артефактов;
после grace контейнеры удаляются, поздний успех не принимается.

Concurrency ограничивает число рабочих запросов/подготовленных текстов, но не
суммарную память модели, манифеста, находок, контекста и JSON/HTML. Большое число
находок или длинные файлы требуют измерений. OOM/timeout/отказ записи дают 2.
Меняйте budgets по результатам [проверки целевой нагрузки](../admin/operations.md),
не используйте увеличение памяти как замену оценке качества детекторов.

## Paths, output и metadata

Вход монтируется read-only, output — отдельно с записью, config/baseline —
отдельными read-only файлами. Output вне клона, его parent существует;
конечный каталог новый или пустой, принадлежит UID оператора и без group/other
permissions. Новые каталоги `0700`, файлы `0600`; права старых не исправляются.
Symlink/output внутри входа/конкурирующий writer отклоняются.

Права private output одинаково требуются Python writer и Docker launcher.
Python writer публикует файлы атомарно по отдельности с fsync/exclusive create;
оба артефакта общей транзакции не имеют. Полный отказ FS может не сохранить
error-report; окончательный process code 2 запрещает считать запуск успешным.

Deployment/checksums/build inventory принимаются только как regular file,
по фактически открытому nonblocking/no-follow FD. Лимит фактического чтения —
4 MiB + 1 byte, oversize отвергается. UTF-8 JSON строгий: без duplicate keys,
NaN/Infinity. FIFO/device/directory/final symlink дают bounded отказ до Docker.
Предки metadata принадлежат доверенному host окружению; это не защита от
активного злоумышленника-хоста. Baseline имеет отдельный [лимит 128 MiB](baseline.md).

## Lifecycle и безопасность запуска

Для каждого scan создаются private Compose JSON и уникальный project
`rullmscan-<UUID>`. `.env` из проверяемого checkout не читается. Два сервиса
соединены единственной `internal` network: без published ports, host network,
Docker socket, credentials и дополнительных networks. Образы запускаются по
immutable reference с явной платформой, actual platform IDs проверяются заранее.
`pull_policy: never`, `--pull never` и `--no-build` запрещают получение images при scan.

Применяются non-root UID/GID оператора, read-only root FS, drop ALL capabilities,
`no-new-privileges`. Writable — tmpfs и output scanner. Container logging driver
`none` препятствует попаданию текстов Analyzer в Docker logs. Read-only bind
не защищает object store от изменения другим хостовым процессом.

Readiness/signature обязательны. Сбой Analyzer отменяет проверку; внешняя модель,
другой image и fallback GPU→CPU не подставляются. SIGINT/SIGTERM пересылаются
scanner, затем убираются только контейнеры/сеть своего точного project label.
При SIGKILL/потере агента cleanup не гарантирован: нужна [процедура восстановления](../admin/operations.md#потерянный-запуск).
Не применяйте broad prune/массовую остановку других проектов.

## Результат launcher

| Поле/код | Значение |
| --- | --- |
| `exit_code=0` | Заданная проверка завершена без находок |
| `exit_code=1` | Заданная проверка завершена с находками |
| `exit_code=2` | Ошибка/неполнота, в том числе инфраструктурная |
| `error` | null либо bounded инфраструктурный код; ошибки анализа находятся в report |
| `project` | Точный run ID для собственного cleanup; отсутствует при раннем preflight |

`verify/export/import` при успехе возвращают `exit_code` и `operation`.
Консоль не содержит значения/контекст/сырые stderr/HTTP bodies. При раннем
отказе нет гарантии JSON/HTML; их наличие и даже старый clean не заменяют
успешный код всего запуска. [Диагностика и коды](errors.md).
