# Воспроизведение проверок

Продукт: `755152b8d658506ddb3da819569270ca46f2ae57`. Dev-изменения этой ветки:
явный `--deployment-lock` в двух harness, bounded capacity probe и документация.
Ниже новые пути, а не приглашение перезаписывать сохранённые outputs.
Полные reports/logs не публикуйте. Нужны trusted assets/images и Docker Desktop
с бюджетами из README; другой сервер проверяется отдельно.

## Подготовка и быстрые группы

Подготовьте `.build/analyzer` по [руководству разработчика](../../docs/development.md).
В отдельном venv установите проект и `requirements-dev.txt`.

```sh
python scripts/analyzer.py verify-context --context .build/analyzer
python scripts/check_cli_tests.py --output-dir .build/validation-next/unit
python scripts/check_git_layer.py --output .build/validation-next/git-host.json
python scripts/check_git_layer.py --docker-image ru-llm-scanner-git-tests:stage3 \
  --output .build/validation-next/git-linux.json
python scripts/check_upstream_tests.py --context .build/analyzer \
  --image ru-llm-scanner-analyzer:stage2-tests \
  --output .build/validation-next/upstream-tests.json
python scripts/check_contracts.py
python scripts/check_documentation.py --output .build/validation-next/documentation.json
```

Test images — отдельные trusted dev artifacts, не штатный launcher. Их фактические
IDs записаны в evidence; один tag без проверки ID не фиксирует содержимое.

## Два walkthrough

Fresh source получен `git archive 755152b`, извлечён в новый каталог с `filter=data`,
без `.git/.build`; создан новый `.venv` Python 3.12.14, установлен `-e .` и
`-r requirements-dev.txt`. Python 3.12 заменяет явный `python3.11` в примере:
руководство допускает host 3.11+. Docker image остался Python 3.11.16.

Далее фактически пройден [build route](../../docs/admin/build.md) с
`WORK=.build/cpu-arm64-build-001`, новым Analyzer tag `cpu-build-001` и scanner
tag `cpu-build-001`. Context/seal/runtime/engine/wheel/scanner-context/deployment
записаны в WORK. Подготовка model/dependency/wheel может использовать сеть;
`analyzer build` использовал pinned local base/BuildKit cache. Scanner build
и все scan/parity процессы offline. Один новый runtime/deployment передан явно
во все следующие команды. Порядок/коды/время — [fresh-steps.json](fresh-steps.json),
IDs/hashes — [runtime-verification.json](runtime-verification.json).

Ready install — другой новый каталог, только launcher из того же commit,
`docs/` и полный export; `images.tar` и прочие package files перенесены hard links
собственного доверенного пакета. Import проверил состав и hashes до load.
Команды выполнялись **base Python 3.12.14 `-I -S`**, без site packages/dev venv;
host Git нужен только для создания контрольного synthetic repo.
Пройдены [installation](../../docs/admin/installation.md) и
[user route](../../docs/user/README.md), с заменой `/opt`/`/srv`/`/data` на новые
доступные пути оператора. Manual prerequisites: создать parents, скопировать
launcher/docs отдельно от export, задать user.name/email, отключить gpg/hooks
контрольного repo. Всё это описано в руководствах. Конфигурация — доверенная
копия `examples/config/scanner.json`; baseline — реальный clean snapshot A.
[Точные шаги и результаты](ready-walkthrough.json).

## Production и ёмкость

После build/export установите переменные на **новый** комплект:

```sh
WORK=.build/cpu-arm64-build-001
SCANNER_LOCK="$WORK/deployment.json"
python scripts/check_docker_integration.py --deployment-lock "$SCANNER_LOCK" \
  --output-dir .build/validation-next/docker
python scripts/check_runtime_faults.py --deployment-lock "$SCANNER_LOCK" \
  --output-dir .build/validation-next/faults
python scripts/check_deployment_extras.py --deployment-lock "$SCANNER_LOCK" \
  --context "$WORK/scanner-context" --package "$WORK/offline-package" \
  --output-dir .build/validation-next/extras
python verification/operations-stage-4/probe.py \
  --deployment-lock "$SCANNER_LOCK" --output-dir .build/validation-next/capacity
```

Fault harness намеренно OOM-kill-ит только свой Analyzer и отменяет другой run.
SIGKILL rehearsal убивает host launcher только собственного synthetic project;
фиксирует -9 и оставшиеся resources, затем применяет точный label-based cleanup.
Docker daemon не перезапускался. Процедура —
[потерянный запуск](../../docs/admin/operations.md#потерянный-запуск).

Probe seed — `deterministic-index-v1`, код генератора сохранён в [probe.py](probe.py).
Cgroup CPU и `memory.peak` читаются через docker exec примерно раз в секунду.
Это наблюдённые максимумы lifetime counters до cleanup, последний интервал
может быть потерян; CPU включает накладные расходы probe, RAM — memory charged
этому cgroup при существующем shared page cache VM, не универсальная потребность
модели. `/tmp` regular-file sizes — только видимые sampled bytes, не пик занятого
диска и не удалённые открытые файлы. JSON/HTML output size измеряется после run.

## Реальный публичный клон

Отдельная network-подготовка, без checkout, установки dependencies/выполнения кода:

```sh
git -c core.hooksPath=/dev/null clone --no-checkout --depth 1 --branch v2.32.5 \
  https://github.com/psf/requests.git .build/validation-next/requests
python verification/operations-stage-4/probe.py --public-only \
  --deployment-lock "$SCANNER_LOCK" --output-dir .build/validation-next/public \
  --public-repo .build/validation-next/requests \
  --public-commit b25c87d7cb8d6a18a37fa12442b5f883f9e41741
```

Повтор Requests использовал `--run-timeout-seconds 900` в новом output. Оба
прогона incomplete, не применять их как baseline. Минимальное воспроизведение
RV-06: извлечь blob `AUTHORS.rst` через `git show COMMIT:AUTHORS.rst` как данные,
поместить в собственный synthetic Git commit и выполнить snapshot. Hash входа,
bounded error и resource/input preservation — [authors-repro.json](authors-repro.json).

Дополнительный no-checkout clone `https://github.com/pallets/itsdangerous.git`,
tag `2.2.0`, проверялся обычным launcher snapshot с `--analyzer-memory 2g` и
`--run-timeout-seconds 300`, без исключений. SHA/tree и полная безопасная сводка —
[public-itsdangerous-verification.json](public-itsdangerous-verification.json).
Этот малый run и два последовательных AUTHORS probes выполнялись на фоне
Requests900; ресурсные данные последнего не являются изолированным benchmark.

Проверяйте commit/tree из [public-source.json](public-source.json). No-checkout
допустим: scanner читает object store. Хэш/permissions/состав всего input дерева,
включая `.git`, сравниваются до/после. Не добавляются исключения ради результата.
Нет ground truth: реальные counts не precision/recall, credentials не проверяются
во внешних сервисах, полные values/context не публикуются.

## Browser/advisories

Browser QA: IAB через cua, demo + synthetic clean/findings/incomplete из свежего
CLI + controlled-transport `tests/integration/html_fixtures.py`. Локальный сервер
на 127.0.0.1, только synthetic copies, затем остановлен. Проверены состояния
search/no matches/category/source/file/group/reset/context/raw/technical,
два raw path с одинаковым display, multiline и Unicode/controls, 1280/390 px.
CSP прочитан без изменения, DOM не содержит внедрённых img/svg/iframe или
внешних script/link assets, console warnings/errors пусты. Это DOM/CSP проверка,
не packet capture. [Наблюдения](browser/browser-observations.json) и screenshots
содержат только синтетические значения.

Inventory извлечён stdlib `importlib.metadata.distributions()` и
`dpkg-query -W -f '${binary:Package}\t${source:Package}\t${Version}\t${source:Version}\n'`
из каждого verified image с `--network none --read-only --user 65534:65534`
и drop ALL/no-new-privileges. OSV querybatch получал уникальные PyPI pairs;
details — GET `/v1/vulns/{id}`, aliases объединены. Debian trixie JSON сопоставлен
с source package/version, fixed_version `0` исключён; остальные fixed сравнивались
`dpkg --compare-versions installed lt fixed` в том же scanner image без сети.
Дубликаты pip/setuptools дополнительно проверены через module.__version__,
module.__file__ и metadata paths. [Итоги и ограничения](dependencies.md).
