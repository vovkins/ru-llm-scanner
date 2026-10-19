# Штатный запуск Docker

На хосте нужны Python 3.11+ (только стандартная библиотека), Docker Engine,
Compose v2+ и **готовые локальные образы**. Проверено: macOS Apple Silicon,
Docker Desktop 29.6.1, Compose 5.2.0, Linux ARM64 внутри VM. Иные версии,
Linux-host UID mapping и AMD64 требуют проверки в целевой среде. Запуск от
root запрещён: используйте отдельного non-root оператора/агента с доступом
к Docker. Доступ к daemon сам по себе является привилегированным доступом хоста.

Сначала выполните [подготовку или offline import](offline-build.md).
В каталоге установленного scanner нужны `scripts/docker_scanner.py` и доверенный
deployment lock. Соседний `ru-llm-proxy`, venv, исходный build context и пакеты
Python на хосте во время сканирования не требуются.

## Первый снимок и переходы

Команды выполняются из каталога scanner. `/data/project` — заранее
подготовленный self-contained Git-клон. Родитель output должен существовать;
сам output — новый либо пустой приватный каталог владельца с правами 0700.
Output располагается вне проверяемого репозитория. Рабочее дерево не меняется.

```bash
python3 scripts/docker_scanner.py verify

python3 scripts/docker_scanner.py snapshot \
  --repo /data/project --commit HEAD --output /data/results/initial

python3 scripts/docker_scanner.py diff \
  --repo /data/project --from COMMIT_A --to COMMIT_B \
  --baseline /data/results/initial/report.json --require-baseline \
  --output /data/results/check-B
```

В output появляются `report.json` и `report.html` (0600, UID/GID оператора).
Значения и контекст полные. Не помещайте output в общий каталог или публичные
CI-артефакты. Права входа не исправляются через chmod/chown: оператор должен
заранее иметь доступ к клону. Пустой существующий output с групповым/публичным
доступом отвергается. Папка сохраняется и при раннем отказе; повторный запуск
использует новую папку либо пустую приватную папку после расследования.

Launcher возвращает **0** — завершено без находок, **1** — завершено с находками,
**2** — ошибка/неполнота, в том числе инфраструктурная. При crash/OOM или раннем
отказе отчётов может не быть. Существование JSON со статусом clean не заменяет
успешный exit 0 всего запуска. Консоль содержит только код, технический run ID
и фиксированный код инфраструктурной ошибки. Сводка находок доступна в отчёте.

`diff` проверяет конечные A/B, не историю. Совместимый доверенный baseline нужен
для подтверждения неизменённых файлов; [точные правила](baseline.md).
Допустимые [Git layout](git-reader.md): локальные объекты, без linked/shared
worktrees, alternates и внешней metadata. Нужные refs/объекты подготавливаются
до запуска; scanner не делает checkout/fetch и не исполняет код клона.

## Конфигурация и ограничения

```bash
python3 scripts/docker_scanner.py snapshot \
  --repo '/data/project with spaces' --commit COMMIT_B \
  --config /data/trusted/scanner.json --exclude 'generated/**' \
  --encoding 'legacy/**=cp1251' --max-file-bytes 10485760 \
  --concurrency 1 --context-lines 2 \
  --ready-timeout-seconds 120 --analyze-timeout-seconds 600 \
  --analyzer-cpus 2 --analyzer-memory 3g \
  --scanner-cpus 1 --scanner-memory 1g \
  --run-timeout-seconds 3600 --stop-grace-seconds 30 \
  --output /data/results/configured
```

Настройки анализа/области соответствуют [CLI](configuration.md).
`--config` и `--baseline` монтируются отдельными read-only файлами.
В Docker-режиме адрес Analyzer всегда `http://analyzer:5001`, даже если config
задаёт другой URL. `--engine-dir` и `--analyzer-url` отсутствуют у launcher:
engine запечатан внутри проверенного scanner image. Другой deployment задаётся
через `--deployment-lock /trusted/deployment.json`; lock и его происхождение
должны быть доверенными. Сканируемый проект не выбирает их через `.env`/config.
Пути и refs передаются массивами argv, символ `$` экранируется для Compose.

По умолчанию Analyzer получает 2 CPU / 3 GiB RAM и 1 GiB tmpfs, scanner —
1 CPU / 1 GiB RAM и 512 MiB tmpfs; tmpfs входит в memory budget, swap дополнительно
не выделяется. Это успешно проверенные лимиты для синтетического code-v1 и
A→B→C, а не гарантия ёмкости для произвольного клона. Стенд: VM 8 GiB / 10 CPU;
параллельные запуски проверены. Для большого отчёта нужен больший scanner RAM:
очередь ограничивает тексты в работе, но не весь результат/HTML/JSON/модель.
OOM даёт 2. Новые лимиты и concurrency сначала проверяйте на своём стенде.

`ready` ограничивает ожидание закреплённой модели, `analyze` — один анализ;
`run-timeout` отсчитывается после preflight образов/путей, перед подготовкой Compose.
Проверка Docker-команд имеет собственные таймауты, поэтому это не точный wall
deadline. Отмена даёт scanner время на запись доступных артефактов и join
локальной CPU-работы; после grace контейнер удаляется. Полный отказ записи
может оставить JSON/HTML разных стадий: атомарность только отдельного файла.

## Изоляция и завершение

Каждый запуск генерирует приватный Compose JSON во временном каталоге и уникальный
проект `rullmscan-<UUID>`. Compose `.env` сканируемого проекта не читается.
Два сервиса используют единственную `internal` network, без published ports,
host network, Docker socket, credentials и дополнительных networks. Проверены
отсутствие default route, non-root UID/GID, root FS read-only, drop ALL capabilities,
no-new-privileges и действительный отказ записи через mount входа.
Writable — только tmpfs и output scanner. Container logging driver — `none`:
тексты Analyzer не попадают в Docker/Jenkins logs.

Образы выбираются по неизменяемой локальной reference ID с явной платформой;
до старта проверяется platform Image ID. `pull_policy: never`, `--pull never`
и `--no-build` запрещают runtime получение образов. Модель/пакеты уже внутри.
Readiness/signature проверяет установленный CLI. Сбой Analyzer отменяет scan;
нет fallback на другой образ, внешнюю модель или GPU→CPU.

SIGINT/SIGTERM launcher направляет scanner как отмену и удаляет только контейнеры/
сеть своего project label. Исходный код и [ADR-0006](decisions/0006-offline-container-lifecycle.md)
описывают владение ресурсами. При SIGKILL, потере daemon/агента cleanup не может
гарантированно выполниться: используйте [восстановление](operations.md).
Нельзя применять `docker system prune` или останавливать чужие проекты.

Проверенные сценарии и ограничения: [этап 6](../verification/stage-6/README.md).
[Пример Jenkins](jenkins.md), [сборка/перенос](offline-build.md).
