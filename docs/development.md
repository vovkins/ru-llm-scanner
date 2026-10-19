# Разработка и проверки

Доступны спецификации, JSON Schema, синтетические отчёты и механизм анализа:
подготовка/сборка Analyzer, API-адаптер и словарь. Доступен внутренний Git API:
снимки/сравнение, классификация и строгая подготовка текста.
Внутренний scan pipeline, профиль и находки/координаты реализованы на этапе 4.
CLI snapshot/diff, renderer и baseline реализованы на этапе 5. Штатный
Docker/Compose и Jenkins ещё не реализованы.

## Структура

| Путь | Назначение |
| --- | --- |
| `docs/` | Контракты, архитектура, границы, решения и инструкции |
| `schemas/report-v1.schema.json` | Структурная схема JSON-отчёта |
| `examples/reports/` | Синтетические отчёты, не результаты работы детекторов |
| `examples/report-fixtures.json` | Исходные тексты/индекс для контрактной проверки |
| `scripts/check_contracts.py` | Dev-проверка схемы, примеров, инвариантов и ссылок |
| `requirements-dev.txt` | Версия инструмента валидации; не зависимости Analyzer |
| `src/ru_llm_scanner/` | Async API-адаптер, словарь, артефакты и инструменты подготовки |
| `git_repository.py`, `git_plan.py`, `text_policy.py` в `src/ru_llm_scanner/` | Изолированное чтение Git, выбор A/B и подготовка text-v1 |
| `scripts/check_git_layer.py`, `docker/git-test.Dockerfile` | Синтетический dev-прогон Git/text, включая Linux без сети |
| `configuration.py`, `engine.py`, `findings.py`, `pipeline.py` в `src/ru_llm_scanner/` | Эффективный профиль, доверенные assets, координаты и bounded scan API |
| `tests/corpus/`, `scripts/check_scan_integration.py` | Независимый code-v1 и реальная offline-проверка pipeline |
| `upstream.lock.json`, `locks/` | Закреплённые источники, constraints и измеренный runtime |
| `patches/`, `docker/` | Минимальная адаптация API и offline inventory helpers |
| `tests/`, `scripts/check_*` | Модульные и изолированные интеграционные проверки |
| `AGENTS.md` | Постоянный порядок согласования и обновления прогресса |

## Запуск доступной проверки

Нужны Python 3.11+, Git и `venv`. Установка инструментов разработки может требовать
индекс пакетов/корпоративное зеркало; сама проверка схемы работает локально.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e . -r requirements-dev.txt
.venv/bin/python scripts/check_contracts.py
git diff --check
```

`jsonschema[format]==4.26.0` закреплён как runtime/dev dependency, включая зависимости
проверки форматов date-time/UUID. Скрипт использует явный
Draft 2020-12 validator и format checker. Данные читаются строгим JSON без
дублирующихся ключей, NaN и Infinity. Внешние `$ref` не используются.

Проверка охватывает схему, все перечисленные примеры, ошибочные сочетания
status/exit/assurance, score/UUID/date, открытый каталог новых категорий,
счётчики, сырые пути, ID, profile/manifest hash, цепочку примеров, координаты
Unicode/CRLF, ссылки внутри Markdown и закрытие code fences.

Она не проверяет реальное Git-дерево, доверие к артефакту, доступность модели,
качество детекторов, автономность контейнеров или HTML. Скрипт предназначен
только для спецификационных fixtures и не является production-валидатором
произвольных отчётов. Runtime не импортирует этот скрипт: отдельный validator находится в
`report_validation.py`, использует упакованную копию schema v1 и смысловые
инварианты. Тождество публичной и packaged schema проверяется unit-тестом.

На этапе 2 добавлены проверки артефактов и async адаптера:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m black --check src tests docker scripts/analyzer.py \
  scripts/check_analyzer_integration.py scripts/check_upstream_tests.py \
  scripts/capture_licenses.py scripts/check_git_layer.py scripts/check_scan_integration.py \
  scripts/check_cli_integration.py scripts/check_cli_tests.py scripts/prepare_scan_engine.py
```

Для словарных parity-тестов сначала выполните `prepare --output .build/analyzer`
по [руководству](analyzer.md); без assets они явно помечаются skipped.
Итоговая проверка этапа требует полного прогона без skipped. Остальные unit-тесты
не требуют Docker. Реальные модельные и upstream-проверки выполняются командами
из руководства, отдельно от unittest/JSON Schema. `black==25.1.0` — dev-tool,
runtime-клиент использует `httpx==0.28.1` из pyproject.toml.

Фактически выполненные проверки, измеренный runtime lock и границы стенда
собраны в [результатах этапа 2](../verification/stage-2/README.md).

Этап 3 добавляет отдельный набор без модели и сторонних Python-зависимостей:

```bash
.venv/bin/python scripts/check_git_layer.py --output .build/stage-3/host-tests.json
```

Он проверяет реальные временные Git-репозитории, SHA-1/SHA-256, pack/shallow,
missing/promisor, сырые пути, изменения деревьев, неизменность входа, hooks/
filters/includes/helpers, лимиты, сигнатуры и строгие кодировки. Linux-прогон
с read-only FS, без сети и от UID 65534 описан в [Git reader](git-reader.md).
Отчёт сохраняет версии, Image ID при Docker и хеши проверенного кода;
[результаты этапа 3](../verification/stage-3/README.md) не являются scan-отчётами.
NER не повторяется для независимого Git-изменения: её исходники/артефакты
на этом этапе не менялись.

Этап 4 добавляет 24 unit test method для strict config/профиля, находок и
pipeline; полный набор теперь содержит 96 тестов. Запуск тот же `unittest`
выше, включая подготовленные словарные assets без skipped. Синтетический
[code-v1](../tests/corpus/README.md) содержит 46 файлов/37 размеченных мест
полного каталога, включая отрицательные примеры. [Реальный offline-прогон](scan-api.md)
выполняется отдельно: техническая parity с Analyzer/словарём не заменяет
оценку exact TP/FP/FN относительно независимой разметки.
[Результаты этапа 4](../verification/stage-4/README.md) сохраняют оба результата
и известные ошибки качества без исходных значений.

Этап 5 добавляет CLI subprocess и negative baseline/output/HTML сценарии.
Полный набор — 123 test method (27 новых), с хешами кода и safe evidence:

```bash
.venv/bin/python scripts/check_cli_tests.py --output-dir .build/stage-5/unit-tests
```

На macOS sandbox может блокировать loopback bind, используемый локальным HTTP
stub в CLI-тестах; нужен разрешённый dev runtime, без внешней сети. При отсутствии
подготовленных assets отдельные тесты skipped; итоговый прогон требует ноль skipped.
Логи assert остаются локально, unit-tests.json содержит только хеши/версии/счётчики.
Реальный [offline CLI-прогон](cli-quickstart.md) проверяет установленный wheel и
engine, отдельный корпус и A→B→C. [Результаты этапа 5](../verification/stage-5/README.md)
отделяют его от HTTP stub/unit и браузерной визуальной QA.

## Стратегия следующих этапов

| Этап | Проверки, которые появятся с реализацией |
| --- | --- |
| 2 (реализовано) | Контракт API, readiness, источник, каталог, словарь, соответствие upstream |
| 3 (реализовано) | Git-деревья, refs, добавления/удаления/переименования, пути, хуки/фильтры, missing objects |
| 4 (реализовано) | Полные файлы, координаты, длинные/многострочные значения, bounded queue/отмена, положительный и отрицательный корпус кода |
| 5 (реализовано) | Реальные отчёты, semantic validation, цепочка baseline, экранирование и визуальная QA HTML |
| 6 | Изолированный Docker, mounts, CPU/GPU, отсутствие внешних соединений, Jenkins артефакты |
| 7 | Сквозная приёмка, актуальность инструкций, обновление Analyzer и откат |

Не добавляем тесты обратимых мелких правок и проверки, которые лишь повторяют
реализацию. Новые тесты должны подтверждать контракт, значимый сценарий или
регрессию. После успешных применимых проверок не расширяем прогон без причины.

## Изменение контрактов

Одновременно обновляйте спецификацию, версию схемы при необходимости, примеры
и негативные сценарии. Изменение смысловой обработки scanner меняет
`scanner_semantics`; изменение профиля исключает старые baseline. Оформление
README не должно менять подпись анализа.

Для документации проверяются работающие относительные ссылки, правдивый статус,
согласованность CLI/JSON и синтетичность данных. Quickstart Docker/Jenkins
добавляется только с проверенной реализацией; будущие документы перечисляются
без ссылок на несуществующие страницы. Новые архитектурные решения отражаются
в [ADR](decisions/README.md), требования — в [матрице](requirements.md).

Текущий этап и следующий подробный план отслеживаются в
[общей задаче](https://github.com/vovkins/ru-llm-scanner/issues/1).
Чекбоксы обновляются по фактическому результату, каждый следующий этап требует
отдельного явного согласования пользователя.
