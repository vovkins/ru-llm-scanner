# Исправления после ревью: RV-01–RV-05

План [#18](https://github.com/vovkins/ru-llm-scanner/issues/18) явно согласован
2026-10-19, включая новую политику Python output. Исходный отчёт —
[ревью](../../docs/review/README.md) на `336feb6`; ветка исправлений начинается
с report commit `fc0dcbf`. Исторические JSON ревью сохранены без изменений.

## Изменения

| Замечание | Результат | Тематический коммит |
| --- | --- | --- |
| RV-01 | Jenkins принимает проверенный объект summary и согласованный код; malformed/type/bool/duplicate/extra fields/stderr/сигнал/отсутствующие private reports дают 2. Ошибки WORKSPACE/status ограничены, чужие файлы не заменяются | `b008c27` |
| RV-02 | Metadata loader открывает nonblocking/no-follow FD, проверяет regular file, читает максимум 4 MiB + 1 byte, сохраняет strict UTF-8 JSON | `6e6cd07` |
| RV-03 | В dev image добавлен jsonschema[format], в curated input — packaged JSON; import/schema smoke предшествует модели | `6f687a7` |
| RV-04 | Две parity-команды используют общий allowlisted workspace, проверяют actual immutable IDs, запускаются без сети/pull/root/capabilities; уникальный ownership label ограничивает cleanup | `792aa00` |
| RV-05 | Final output FD должен принадлежать UID оператора и не иметь group/other permissions. Существующие права/данные не исправляются | `71588fd` |

Каталог `0700` — обычный разрешённый вариант, `0755`/`0777`/чужой owner
отвергаются. Сохраняются symlink/concurrent/race guards, atomic per-file
publication и `0600` файлов. Профиль распознавания и baseline semantics не менялись.
Текущие [CLI](../../docs/cli-quickstart.md), [Jenkins](../../docs/jenkins.md),
[metadata](../../docs/docker-quickstart.md), [Analyzer](../../docs/analyzer.md)
и [dev recipe](../../docs/scan-api.md) обновлены вместе с поведением.

## Выполненные проверки

Среда: macOS ARM64, host Python 3.12.14, Docker 29.6.1/Compose 5.2.0,
CPU Linux ARM64 внутри Docker Desktop. Runtime выполнялся без внешнего маршрута.

| Свидетельство | Фактический результат |
| --- | --- |
| [Полный unit](unit-tests.json) | 144 tests, 0 failures/errors/skipped, подготовленные trusted assets; HTTP stub отделён от модели |
| [Dev scan](scan-verification.json) | Новый dev image, import/schema smoke, code-v1 46/46 direct parity, исходные координаты/value/context |
| [Raw/patched](offline-verification.json) | 77/77 NER parity, 4 dictionary cases, существующие quality gates прошли; ограниченный curated mount |
| [Установленный CLI](cli-verification.json) | Wheel совпадает с source/schema, 9 реальных сценариев 0/1/2, snapshot/diff/baseline/error |
| [Code-v1 установленного wheel](installed-code-verification.json) | 46/46 direct parity; TP 33, FP 13, FN 4 на независимой разметке |
| [Production acceptance](acceptance-verification.json) | 16 запусков: snapshot/diff/baseline, A=B, merge/history, encoding/scope и hostile Git; вход не менялся |
| [Permissions/Jenkins/metadata](extras-verification.json) | 14 случаев, в том числе installed Python output 0700/0755/0777, Jenkins clean/diff/findings/error/untrusted baseline, transfer checksum/platform ID/context integrity |
| [Сверка границ](completion.json) | Те же model/assets/profile/default locks/images; proxy tracked clean; 7 чужих контейнеров без restart; собственных ресурсов не осталось |

Unit-регрессии проверяют fake launcher subprocess и signal forwarding/reaping,
FIFO без writer с внешним safety timeout до Docker, strict/oversize metadata,
private/public/foreign-owner output и shared parity preflight/mounts/cleanup.
Чужой owner моделируется другим UID без chown/root; это не проверка Linux-host ACL.
Положительный 0700 installed-output случай намеренно использует missing config:
он подтверждает публикацию валидного error-report без запуска модели. Штатные
clean/findings дополнительно подтверждены реальными CLI/Compose/Jenkins прогонами.

Code-v1 сохранил TP 33 / FP 13 / FN 4 (precision 71.74%, recall 89.19%).
Parity не устраняет модельные пропуски. NER quality gates на другом корпусе
не подменяют независимую оценку code-v1. Full reports/private logs остаются
в `.build/operations-fixes/`, в Git включены только hashes/counts/синтетические метрики.

## Локальные образы

Новые образы только для этой проверки, без публикации и автоматического принятия:

- Dev tag `ru-llm-scanner-scan-tests:operations-fixes`: reference
  `sha256:3dbc2733242136571767418fb549ef12ba1ac33cda78f197fdeba872c5ae9944`.
  Python 3.11.16, httpx 0.28.1, jsonschema 4.26.0; фактические format dependencies
  и platform ID сохранены в completion.json. Online-часть рецепта готовит dependencies;
  import/model test выполняются offline.
- Scanner tag `ru-llm-scanner:operations-fixes`: reference/platform ID
  `sha256:6d4056589f5c08e2a8c202f996bc2414ae9ac7aec8b5de685ce4aa73fc9b389b`.
  Wheel SHA-256 `36b9c21ab66cd7427b0a342ff420989a896f160b52f60c27df41db494194969c`.
  Сборка offline из проверенных dependencies этапа 6 с заменой только scanner wheel.

Штатный deployment lock по-прежнему описывает предыдущий образ. Исправление
установленного Python CLI находится в новом wheel/image; существующие образы
не обновляются от редактирования исходников. Новый deployment для проверок —
`.build/operations-fixes/deployment.json`, default lock не перезаписывался.

## Воспроизведение

Нужны dev environment, prepared `.build/analyzer`, соответствующий runtime lock,
локальный закреплённый Analyzer и валидированный dependency context этапа 6.
Это повтор dev-проверки, не инструкция чистой установки и не runtime-зависимость
пользователя от `.build/`. Для каждого нового прогона выбирайте новый output.
Здесь `python` — Python venv с dependencies проекта и Black.

```sh
python scripts/check_cli_tests.py --output-dir .build/recheck-unit
python scripts/check_analyzer_integration.py \
  --context .build/analyzer \
  --runtime-lock locks/analyzer-cpu-linux-arm64.runtime.lock.json \
  --output-dir .build/recheck-parity

mkdir -p .build/recheck-dev-context
cp docker/scan-test.Dockerfile .build/recheck-dev-context/Dockerfile
docker build --pull=false --platform linux/arm64 \
  -t ru-llm-scanner-scan-tests:recheck .build/recheck-dev-context
python scripts/check_scan_integration.py \
  --context .build/analyzer \
  --runtime-lock locks/analyzer-cpu-linux-arm64.runtime.lock.json \
  --scanner-image ru-llm-scanner-scan-tests:recheck --output-dir .build/recheck-scan

python -m pip wheel --no-deps --wheel-dir .build/recheck-wheels .
python verification/operations-stage-2/prepare_context.py \
  --base-context .build/stage-6/context \
  --wheel .build/recheck-wheels/ru_llm_scanner-0.1.0.dev0-py3-none-any.whl \
  --context .build/recheck-scanner-context
python scripts/build_scanner.py build --context .build/recheck-scanner-context \
  --tag ru-llm-scanner:recheck --deployment-lock .build/recheck-deployment.json
python scripts/check_cli_integration.py \
  --context .build/analyzer \
  --runtime-lock locks/analyzer-cpu-linux-arm64.runtime.lock.json \
  --scanner-image ru-llm-scanner:recheck --output-dir .build/recheck-cli
python scripts/check_acceptance.py --deployment-lock .build/recheck-deployment.json \
  --output-dir .build/recheck-acceptance
python scripts/check_deployment_extras.py --deployment-lock .build/recheck-deployment.json \
  --context .build/recheck-scanner-context --package .build/stage-6/offline-package \
  --output-dir .build/recheck-extras
python scripts/check_contracts.py
python -m black --check src tests docker scripts examples/jenkins \
  docs/review/reproduce.py verification/operations-stage-2/prepare_context.py \
  --extend-exclude 'check_contracts\.py'
git diff --check
```

Context helper проверен сравнением полного inventory с фактически собранным
context. Он не скачивает/обновляет dependencies и не заменяет штатный fresh-build
путь. Для новой среды сначала нужны [подготовка dependencies](../../docs/offline-build.md)
и отдельный последующий clean walkthrough.

GPU, AMD64, другой физический offline host, настоящий Jenkins controller,
новые capacity measurements/advisory database не проверялись в этом этапе.
Полноценные руководства по ролям — следующий отдельно согласуемый этап;
merge/release/registry/лицензия/внешние настройки не изменены.

[Подробный план этапа 3 — #20](https://github.com/vovkins/ru-llm-scanner/issues/20)
подготовлен с чекбоксами и ожидает явного согласования. Работа над ним не начата.
