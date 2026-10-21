# Разработка и проверки

Пользователь готового Docker-комплекта следует [своему руководству](user/README.md).
Подготовка images — [маршрут администратора](admin/build.md). Здесь описаны
изменения scanner, внутренние API и dev-проверки, а не prerequisites обычного scan.

## Окружение

Нужны POSIX, Python 3.11+, Git и venv. Установка может обращаться к одобренному
индексу/зеркалу; локальные проверки не должны скачивать данные незаметно.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip==26.2.1
.venv/bin/python -m pip install -e . -r requirements-dev.txt
```

`httpx==0.28.1`, `jsonschema[format]==4.26.0` закреплены в pyproject.toml;
Black 25.1.0 — dev-tool. Build backend закреплён отдельно. Host Docker launcher
использует stdlib, эти библиотеки ему не нужны.

## Структура

| Путь | Назначение |
| --- | --- |
| `src/ru_llm_scanner/` | Git/text, Analyzer/dictionary client, pipeline, config/profile, baseline, output/renderer |
| `scripts/docker_scanner.py` | Stdlib host runtime, private Compose, export/import/verify |
| `scripts/analyzer.py`, `src/ru_llm_scanner/upstream.py` | Явная подготовка/build/seal закреплённого upstream |
| `scripts/build_scanner.py`, `docker/scanner.Dockerfile` | Малый verified context, offline scanner image и deployment |
| `upstream.lock.json`, `locks/`, `patches/` | Reviewed source, constraints, измеренные locks и точные адаптационные patches |
| `schemas/report-v1.schema.json` | Публичная schema; packaged копия лежит в `src/ru_llm_scanner/` |
| `examples/config/`, `examples/reports/`, `examples/demo/` | Синтетические config/JSON/HTML, документационные примеры не baseline |
| `tests/`, `tests/corpus/`, `tests/integration/` | Unit/stub, frozen quality fixtures и настоящие isolated integration checks |
| `docs/user/`, `docs/admin/`, `docs/reference/` | Маршруты двух ролей и канонические контракты |
| `docs/architecture.md`, `docs/decisions/` | Устройство и принятые решения |
| `verification/` | Версионированные безопасные evidence и границы результатов |
| `.build/` | Локальные private assets/results; не публикуются |

Архитектура: [обзор](architecture.md), [ADR](decisions/README.md),
[требования](requirements.md). API: [Git](git-reader.md), [scan](scan-api.md),
[Analyzer](analyzer.md), [dev CLI](cli-quickstart.md).

## Группы проверок и assets (TEST-01)

| Группа | Предусловия | Что подтверждает |
| --- | --- | --- |
| Contracts/documentation | Dev dependencies, без `.build/analyzer` и Docker | Schema/examples/links, config/demo/документированные параметры |
| Изолированный Git/text | Git, POSIX; Docker только для отдельного Linux-варианта | Реальные synthetic repositories и security/text contracts, без модели |
| Полный unit | **Prepared `.build/analyzer`**, dev dependencies; локальный HTTP stub | Собственные контракты и регрессии; не качество модели |
| Upstream subset | Curated context и test image; offline CPU recipe наследует модель, subset не выполняет inference | Закреплённые synthetic upstream fixtures |
| Raw/patched/scan/CLI | Sealed Analyzer с моделью, подходящий dev/installed scanner image и locks | Реальная модель, parity/coordinates и independent quality |
| Production acceptance | Готовые verified images/deployment, Docker/Compose | Штатные snapshot/diff/baseline/isolation/lifecycle |

Часть dictionary и CLI unit жёстко использует `.build/analyzer`.
Если его нет, unittest помечает группы skipped. **Passed со skipped не является
полным прогоном.** Это известное предусловие TEST-01, не исправленное перестановкой
документации. Не удаляйте обязательные проверки и не подменяйте assets фиктивными.

Для full unit сначала подготовьте pinned tracked assets (модель им не нужна):

```sh
.venv/bin/python scripts/prepare_unit_assets.py --source /trusted/ru-llm-proxy
.venv/bin/python scripts/analyzer.py verify-context --context .build/analyzer
```

Output должен отсутствовать. Если валидный `.build/analyzer` уже есть, проверьте
его, не перезаписывайте автоматически. Явный `--fetch` вместо `--source` допустим
только на стадии подготовки. Context другого пути можно использовать в integration
через аргумент, но существующие asset-required unit ожидают именно этот путь.

Helper сохраняет исторический source/runtime fixture этих unit и соответствующие
constraints отдельно от новых build profiles. Он не скачивает модель и не собирает
images; ARM64 metadata fixture не означает ARM64 inference на AMD64.
Для новых контейнеров используйте текущий профиль из [admin build](admin/build.md).
Нативный workflow `check-cpu-platforms.yml` отдельно выполняет настоящую модель,
полный Requests, empty-store installation, fault/quality проверки обеих архитектур
и Jenkins AMD64. [Текущий source и протоколы](../verification/linux-amd64/README.md).

В draft PR автоматически идут быстрые unit/contracts/docs/format проверки.
Полный native workflow запускается вручную через `workflow_dispatch` либо
автоматически для PR, переведённого в ready for review. Коммиты с протоколами
не требуют повторного model inference при неизменных material inputs;
соответствие inputs принятому native run проверяется при итоговой приёмке.

## Быстрые проверки

```sh
.venv/bin/python scripts/check_contracts.py
.venv/bin/python scripts/check_documentation.py
.venv/bin/python scripts/check_git_layer.py --output .build/git-host-tests.json
.venv/bin/python scripts/check_cli_tests.py --output-dir .build/unit-new
.venv/bin/python -m black --check src tests docker scripts examples/jenkins \
  docs/review/reproduce.py verification/operations-stage-2/prepare_context.py \
  --extend-exclude 'check_contracts\.py'
git diff --check
```

Contracts используют явный Draft 2020-12 validator/format checker, локальные `$defs`,
strict JSON, счётчики/profile/manifest/coordinates и semantic examples. Runtime
никогда не импортирует dev checker; отдельный `report_validation.py` валидирует
packaged schema и доступные связи полей. Одна Schema не доказывает наличие Git-объекта
или доверенное происхождение baseline.

`check_documentation.py` сверяет sample config с defaults, documented option sets,
строгий kind примера и воспроизводимость demo через штатный renderer. Для регенерации:

```sh
.venv/bin/python scripts/check_documentation.py --write-demo
```

Он не принимает пользовательские отчёты. JSON demo копируется из synthetic
`contract_example`; только локальный dev-вызов renderer допускает этот kind с
полной semantic validation. Runtime остаётся строгим. [Подробности](../examples/demo/README.md).
HTML browser acceptance, clean installation walkthrough и capacity/advisory
checks выполняются отдельной матрицей, не объявляются результатом этой команды.

Full unit collector требует 0 skipped и сохраняет hashes/versions/counts;
неопубликованный AMD64 кандидат прошёл [170 host unit](../verification/linux-amd64/host-unit-summary.json).
сырой log остаётся локальным. Последнее evidence содержит
[155 tests на слитом main](../verification/operations-main-integration/unit-tests.json), не обещание
неизменного количества тестов при будущих правках.
[Итоговая приёмка](../verification/operations-stage-5/README.md) повторно сверила
все 64 source hashes предыдущего набора; после слияния полный unit выполнен заново.

## Реальная модель и контейнеры

[Admin build](admin/build.md) проводит один новый runtime lock через seal/parity/
engine/CLI и получает отдельный deployment. [Analyzer dev](analyzer.md) описывает
upstream subset и API. [Scan API](scan-api.md) содержит малый dev recipe с
httpx/jsonschema и import/schema smoke до модели.

Примеры команд принимают явные `--context`, `--runtime-lock`, `--scanner-image`
и новый output. Для кандидата с другим source lock scan/CLI harness принимает
`--source-lock`; штатные locks для этого не меняют. Shared `parity_verification.py`
готовит allowlisted workspace, проверяет actual image IDs, запрещает UID 0 и pull,
чистит только собственный ownership label. Не монтируйте весь checkout в test image.

Production-примеры для **выбранного** проверенного deployment:

```sh
.venv/bin/python scripts/check_acceptance.py \
  --deployment-lock /trusted/deployment.json --output-dir .build/acceptance-new
.venv/bin/python scripts/check_deployment_extras.py \
  --deployment-lock /trusted/deployment.json \
  --context /trusted/scanner-context --package /trusted/offline-package \
  --output-dir .build/extras-new
```

Extras проверяет installed Python output независимо от Compose и даёт Jenkins
малую trusted installation с явным lock. Исторические upgrade/rollback helpers
закрепляют конкретные согласованные версии; это не автоматическое принятие upstream.
[Результаты и различие quality/parity](../verification/README.md).

## Правила изменения

Запускайте применимые проверки: документация сама по себе не требует повторного
NER, а изменение распознавания не подтверждается только schema/unit stub.
После успешной проверки повтор нужен при новом изменении, отказе или нерешённом риске.
Новые тесты должны проверять значимый контракт/регрессию, не повторять оформление.

Контракт меняется вместе со схемой, примерами и правилами совместимости.
Смысловой алгоритм меняет `scanner_semantics`, detection/scope fingerprint —
допуск baseline; оформление README профиль не меняет. Не ретюньте модель/разметку
ради прохождения quality checks. Сохраните полный каталог и отдельный словарь.

Все данные только синтетические, реальные reports/credentials/proxy configs/weights
в Git не включаются. Историческое evidence не переписывается как новый passed.
[CONTRIBUTING](../CONTRIBUTING.md), [SECURITY](../SECURITY.md),
[лицензирование](licensing.md). Текущий цикл/согласования — [#16](https://github.com/vovkins/ru-llm-scanner/issues/16);
каждый следующий этап получает отдельный подробный план и явное согласование.
