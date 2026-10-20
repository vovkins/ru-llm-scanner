# DEP-01/DEP-02: чистый закреплённый комплект

План [#24](https://github.com/vovkins/ru-llm-scanner/issues/24) согласован
2026-10-19. Ветка построена поверх [RV-06](../operations-ner-windowing/README.md).
Это результаты отдельного комплекта; итоговый Requests, runtime gates и оба walkthrough завершены и зафиксированы ниже. После отдельного согласования PR #29 включён в main: [интеграция](../operations-main-integration/README.md). Прежние images/default deployment сохранены.
Принятия остаточных рисков, merge/release/tags/публикации нет.

## Выбор и воспроизводимость

| Вход | Прежний комплект | Кандидат |
| --- | --- | --- |
| CPython | 3.11.16 | 3.11.17, официальный base по digest |
| Transformers | 4.57.6 | 5.20.2 |
| huggingface-hub / tokenizers | 0.36.2 / 0.22.2 | 1.33.0 / 0.23.1 |
| FastAPI / Starlette | 0.115.14 / 0.46.2 | 0.149.0 / 1.9.0 |
| urllib3 | 2.7.0 | 2.8.0 |
| pip / setuptools / wheel | Смешанные metadata; scanner pip 24.0 | 26.2.1 / 84.1.0 / 0.48.0 |
| BERT / spaCy / dictionary | Закреплённые artifacts | Те же files/tree hashes |

huggingface-hub 2.2.0 несовместим с ограничением tokenizers `<2`;
resolver проверил набор 1.33.0. [Artifact lock](../../locks/offline-cpu-linux-arm64.artifacts.json)
содержит 132 artifacts: wheels production/tests, Debian closure и прежнюю модель.
Для каждого указаны HTTPS URL, размер, SHA-256 и назначение. Python constraints
полные и точные. [Порядок подготовки/build/seal](../../docs/admin/build.md).

Source prepare остаётся без сети. `prepare_offline_analyzer.py` создаёт новый
полный context из hash-cache; только `--download` разрешает получение отсутствующих
файлов. Scanner prepare использует `--artifact-cache`/`--download-artifacts`.
Повреждённые bytes, symlinks, неверный closure и hashes отклоняются. Сборка
выполняет offline dpkg и pip `--no-index --no-deps`. BuildKit FROM resolver может
отдельно обращаться к registry за metadata; `--network none` ограничивает RUN.

## DEP-02 и совместимость

Прежняя multi-stage recipe копировала `/usr/local` поверх свежего Python base:
старые dist-info оставались рядом с новыми. Новая recipe создаёт чистый package
tree до установки полного wheel closure. Это сборочная процедура, не удаление
metadata работающего образа. Probe отклоняет повторяющиеся normalized names,
даже с одинаковой версией, и сравнивает импортированные pip/setuptools/wheel с
inventory. Scanner проверяет то же.

Transformers 5 удалил tokenizer helpers. [Точный patch](../../patches/transformers-v5-tokenizer.patch)
сохраняет single-sequence BERT input `[CLS] + content + [SEP]` и нулевые token
types; неправильные special IDs вызывают отказ. Модель/пороги/разметка сохранены.
Последовательные patches одного файла требуют совпадения каждого `before` с
предыдущим `after`; перестановка отклоняется до экспорта.

Прошли [478 upstream tests](upstream-tests.json), [96 NER tests](ner-regressions.json), [77 NER/4 dictionary parity](offline-verification.json), [46 code-v1](scan-verification.json)
direct parity с TP 33 / FP 13 / FN 4. Прямое сравнение старого NER-кандидата и
новых библиотек на [всех 77 случаях](detection-drift.json): ноль изменений обнаружений и maximum score
absolute delta **0.0**. Это результат корпуса, не гарантия для любого ввода.
Новый image/profile требует нового snapshot/baseline.

## Advisory disposition

[Сборщик](../../scripts/check_dependency_advisories.py) отправляет только публичные
package names/versions verified images. Repository/report input отсутствует.
UTC timestamps, response SHA-256/ETag/Last-Modified сохранены в [fetch evidence](final-fetches.json).
Scanner во время анализа к advisory-сервисам не обращается.

[23 PyPI alias groups](pypi-dispositions.json) разобраны по вызываемым функциям,
build/runtime и платформе. [Повторный audit окончательных images](final-images.json): 91 уникальная пара
name/version, **0 OSV matches**. Для `last_affected` не придуман fixed event.
Это не сертификат отсутствия уязвимостей.

[Native dispositions](native-dispositions.json) сохраняют все 185 прежних records.
Все 42 с известной более новой fixed version исправлены по фактическим версиям
и `dpkg` comparison. В кандидате остаются 139 records без указанной fixed version:
55 `unimportant`, 84 `not yet assigned`. Они не объявлены исправленными. Четыре прежние строки относились к разным версиям одного source/advisory и в новом одинаковом closure объединены; 185−42 и 139 поэтому не равны.
Для каждого описаны API/предпосылка, supported workflow и источник; source match
не доказывает запуск уязвимого инструмента или исчерпывающую достижимость.

Первоначально владельцу были оставлены пять version matches. Точечная проверка
2026-10-20 установила неприменимость CVE-2026-95619 к фактической системной
ARM64 libstdc++: используется неуязвимый путь `posix_memalign`.
[Подробный разбор и ограничения](native-risk-detail.md),
[измеренные evidence](native-reachability.json). По остальным **четырём** записям
владелец 2026-10-20 [явно принял риск для закрытого контура](risk-acceptance.md);
ожидающего решения владельца больше нет. Ни одна package version этим разбором не
изменена; отсутствие уязвимого пути не означает установку исправления.

### Пять версионных совпадений и их применимость

| Advisory | Установленный source/version | Условие и оценка |
| --- | --- | --- |
| [CVE-2026-102010](https://security-tracker.debian.org/tracker/CVE-2026-102010) | gcc-14 14.2.0-19 | Ошибка `erase_if` binary heap в libstdc++; штатный вызов не установлен, полного native call graph нет |
| [CVE-2026-95619](https://security-tracker.debian.org/tracker/CVE-2026-95619) | gcc-14 14.2.0-19 | Неприменимо к исследованной системной ARM64 library: `operator new` использует `posix_memalign`, исключённый upstream из affected path; [evidence](native-reachability.json) |
| [CVE-2026-19542](https://security-tracker.debian.org/tracker/CVE-2026-19542) | glibc 2.41-12+deb13u4 | `tdelete` глубокого дерева, предпосылка порядка миллиона узлов; такой маршрут scanner не установлен, исключение всех библиотечных вызовов не доказано |
| [CVE-2026-27171](https://security-tracker.debian.org/tracker/CVE-2026-27171) | zlib 1:1.3.dfsg+really1.3.1-1 | CPU DoS в CRC combine APIs; локальный Git использует zlib, исчерпывающего доказательства достижимости/недостижимости нет |
| [CVE-2026-85091](https://security-tracker.debian.org/tracker/CVE-2026-85091) | zlib 1:1.3.dfsg+really1.3.1-1 | Nonblocking gzwrite/gzprintf после stall; scanner не вызывает gz API напрямую; Debian всё ещё помечает версию vulnerable, range обсуждается |

Четыре остаточных риска DEP-01 приняты владельцем для закрытого контура;
`fixed_in_candidate: false` и технические ограничения оценки сохранены.
Non-root/read-only/network isolation и RAM/time budgets ограничивают последствия,
но не исправляют библиотеки. Итоговая приёмка отдельно согласована и выполнена:
[результат #25](../operations-stage-5/README.md).

## CPython и встроенные библиотеки

[Vendor inventory](python-vendor-inventory.json): CPython 3.11.17, OpenSSL 3.5.7,
Expat 2.8.5, zlib 1.3.1, SQLite 3.46.1. CPython официального image не покрывается
Debian python package audit, поэтому рассмотрен отдельно.
[Релиз 3.11.17](https://www.python.org/downloads/release/python-31117/) содержит
исправления float formatting, TLS arguments/SNI, tar filters, ZIP decompression,
IDNA и urllib credential schemes. Runtime читает Git blobs, не извлекает
пользовательские архивы. Host Python подготовки проверяется отдельно: image
его не обновляет.

Встроенный Expat 2.8.5 не равен Debian libexpat 2.9.0. По
[changelog 2.9.0](https://github.com/libexpat/libexpat/blob/R_2_9_0/expat/Changes)
`CVE-2026-102633` относится к 32-bit, кандидат AArch64; `CVE-2026-77214` требует
неправильной длины XML_ParseBuffer. Scanner не парсит SVG/XML, это текстовый input.
В [CPython binding](https://github.com/python/cpython/blob/v3.11.17/Modules/pyexpat.c)
чтение ограничено размером buffer и передаётся фактическая длина. Это оценка пути,
не исправление встроенной библиотеки. Новый XML/import маршрут потребует переоценки.

Audit ограничен датой источников. Полный native wheel SBOM, неизвестные проблемы,
OS хоста/daemon и Jenkins controller не покрыты. [License inventory](analyzer-licenses.json)
описывает сохранённые package notice files. Лицензия scanner не выбиралась.

Для zlib `CVE-2026-85091` описание upstream range и статус Debian расходятся: [tracker](https://security-tracker.debian.org/tracker/CVE-2026-85091) помечает trixie 1.3.1 как vulnerable и ссылается на обсуждение диапазона. Запись не исключена только по номеру версии. Изменение stable native closure или собственный backport потребует отдельной проверки совместимости и provenance; sid-пакеты в кандидат молча не добавлялись.

## Окончательный комплект и проверки

[Runtime lock](candidate.runtime.lock.json) и [deployment lock](candidate.deployment.json) фиксируют отдельные локальные images, не меняя штатный комплект. Это записи измерения, а не опубликованный registry/release. Source checkpoint для новой сборки — `2588571`; NER parent — `5097ea5`.

[Fresh walkthrough](fresh-walkthrough.json) пройден из `git archive` в отдельном каталоге без `.git`, с новым venv: source prepare, cache-only полный context, offline RUN build, seal, реальная parity, engine/wheel, scanner build, verify, [9 CLI scenarios](cli-verification.json), export. Online шаги установки dev dependencies/build backend выделены. Использовались доступный официальный base, доверенный hash-cache и Docker store того же стенда; сборка не заявлена cache-free/на другом физическом host.

[155 host tests](unit-tests.json) прошли без skips. Первый запуск внутри sandbox не мог bind loopback HTTP fixtures; после выполнения с разрешённым локальным loopback прошёл весь набор. Пропусками эту проверку не заменяли. [Проверка документации](documentation.json) не подменяет runtime acceptance. Эксплуатационные gates и полный Requests завершены последовательно; результаты приведены ниже.

## Воспроизведение runtime gates

Сначала пройти [fresh build](../../docs/admin/build.md) до export; выбрать новые
пути результатов и использовать один и тот же комплект. Здесь `SCANNER_CONTEXT`,
`DEPLOYMENT`, `PACKAGE` относятся к новой сборке, `OLD_DEPLOYMENT` —
к сохранённому проверенному rollback. Все outputs вне сканируемого клона и новые.

```sh
python scripts/check_acceptance.py --deployment-lock "$DEPLOYMENT" \
  --output-dir .build/check-next/acceptance
python scripts/check_docker_integration.py --deployment-lock "$DEPLOYMENT" \
  --output-dir .build/check-next/docker
python scripts/check_runtime_faults.py --deployment-lock "$DEPLOYMENT" \
  --output-dir .build/check-next/faults
python scripts/check_deployment_extras.py --deployment-lock "$DEPLOYMENT" \
  --context "$SCANNER_CONTEXT" --package "$PACKAGE" --output-dir .build/check-next/extras
python scripts/check_upgrade_rollback.py --old-deployment "$OLD_DEPLOYMENT" \
  --current-deployment "$DEPLOYMENT" --output-dir .build/check-next/rollback
python verification/operations-ner-windowing/probe.py \
  --deployment-lock "$DEPLOYMENT" --output-dir .build/check-next/capacity
```

Выполнять последовательно: acceptance/Docker harness сохраняет все запущенные
контейнеры стенда, поэтому завершение параллельного теста меняет его исходный
snapshot. Прежние незавершённые параллельные измерения не засчитаны. Sampler
теперь находит scanner по обоим bind mounts — input **и уникальному output**;
два runs одного клона не могут принять контейнер друг друга. Отдельная unit
регрессия проверяет это и исчезновение контейнера между ps/inspect.

Для Requests использовать доверенный локальный no-checkout клон `psf/requests`
без выполнения его кода. Получение публичного клона — отдельная online-подготовка.
Scanner snapshot читает tracked blobs закреплённого commit:

```sh
python verification/operations-ner-windowing/probe.py \
  --deployment-lock "$DEPLOYMENT" --output-dir .build/check-next/requests \
  --public-only --public-repo "$REQUESTS" \
  --public-commit b25c87d7cb8d6a18a37fa12442b5f883f9e41741 \
  --run-timeout-seconds 2400 --analyze-timeout-seconds 1800 --analyzer-cpus 8
```

`probe-summary-*.json` содержит только counts/hash/метрики; `report.json`,
`report.html` и console assertion logs остаются приватными даже для публичного
репозитория. Наличие находки не доказывает действительность credentials.
Capacity использует synthetic known fixtures, Requests не имеет ground truth.
Polling cgroup включает overhead измерения и может пропустить последний интервал;
максимум tmp regular-file sizes не является пиком диска. Стенд общий с семью
работающими контейнерами; эти времена не являются изолированным benchmark.

Повтор advisory — отдельная явно online операция, только names/versions:

```sh
python scripts/check_dependency_advisories.py --deployment-lock "$DEPLOYMENT" \
  --output-dir .build/check-next/advisories
```

## Полный Requests

[Окончательный snapshot](public-requests.json) закреплённого commit перечислил все
132 объекта: **119 analyzed / 13 unsupported / 0 errors**, без exclude/inherited/
unverified. Код **1**, **612 кандидатов**, assurance `snapshot_verified` в scope
`text-v1`. Полные AUTHORS, tests/test_requests.py и requests-logo.svg обработаны.
13 объектов классифицированы как image/PDF/symlink; их содержимое не заявлено
проанализированным. Нет ground truth и внешней проверки действительности credentials.
Этот отчёт с находками не является clean baseline.

Время **733.927 s**, 8 CPU / Analyzer 3 GiB / scanner 1 GiB; budgets 1800 s analyze,
2400 s total. Наблюдаемый cgroup memory.peak: Analyzer 1116069888 bytes, scanner
100380672 bytes. Общий объём JSON/HTML **72433959 bytes**: длинные строки SVG
увеличивают контекст и размер отчёта, поэтому исходный размер клона не определяет
retention/память renderer. Это измерение на общем стенде, не SLA и не проверка
интерактивности огромного HTML в браузере.

[Сравнение с предыдущим quarter-only кандидатом](public-detection-comparison.json):
на всех **118 общих успешно обработанных файлах 581 finding совпал точно**, включая
value/context/coordinates/score/source/rule_id; исключены только report-specific IDs.
Добавленные **31** относятся к ранее отказавшему tests/test_requests.py. Это отдельная
проверка стабильности на публичном вводе, не оценка precision/recall. Полные значения
и оба отчёта остаются приватными. Вход не изменён, собственный public-run очищен.

При первом запуске дополнительных gates по ошибке был передан Analyzer context в `check_deployment_extras.py`, ожидающий **scanner build context**. Проверки permissions/Jenkins/transfer прошли, затем проверка scanner inventory отказала до изменения context. Эта попытка не засчитана; повтор [прошёл с правильным `SCANNER_CONTEXT`](extras-verification.json). Product sources/images не менялись.

## Runtime, перенос и сохранность

| Проверка | Итоговый evidence |
| --- | --- |
| Snapshot/diff/history boundary/strict baseline | [16 scenarios](acceptance-verification.json) |
| Compose isolation/параллельные runs/ошибки | [25 cases](docker-verification.json) |
| Реальные OOM и отмена во время analysis | [2 cases](fault-verification.json) |
| Permissions/Jenkins adapter/transfer negatives/context tamper | [14 cases](extras-verification.json) |
| Отдельное обновление и откат, несовместимый baseline | [8 runs](upgrade-verification.json) |
| Synthetic 10/100/1000 files, concurrency 2, long text, limit, 128 findings | [7 cases](capacity-verification.json) |
| Git/text в Linux test image | [41 tests](git-linux.json), отдельный прежний dev image для неизменного Git/text слоя |
| Установка из готового offline-пакета | [Ready walkthrough](ready-walkthrough.json), stdlib Python `-I -S` |
| Отмена большого SVG и последующий запрос на окончательном image | [Cancellation/recovery](cancellation.json), 2 CPU, network none |
| Сохранность и cleanup | [Preservation](preservation.json) |

Ready installation содержит launcher/docs/package, без src/venv/.git/proxy/build
contexts. Каждый scan запущен из этого каталога с явным deployment; input неизменен,
private directories 0700 и reports 0600. Проверены clean/findings/error, snapshot A/B,
diff/strict/equal, config/encoding/size flags, неправильный ref и public-output отказ.
Пакет импортирован и IDs проверены. Hard links использованы только для доверенной
копии завершённого export на том же host; другой физический host не проверялся.

[Runtime gates](runtime-gates.json) фиксируют успешные команды после исправления
параметра context. Отменённый HTTP SVG не засчитан analyzed; следующий запрос
успешен после bounded capacity rejection. Core error priority и required NER
не ослаблялись. [Retained notices](retained-notices.json) содержат 72 Analyzer/28
scanner distributions и hashes найденных Python/native notices; отсутствие metadata
не означает отсутствия условий лицензии и не является полной SBOM.

Main `336feb6`, default runtime/deployment, прежние images, proxy tracked tree,
model/dictionary/spaCy tree и frozen corpus сохранены. Все семь чужих контейнеров
с прежними Running/StartedAt. Собственные Compose containers/networks очищены,
prune/остановки чужих проектов не выполнялись. Реальные полные отчёты приватны.
DEP-02 и RV-06 исправлены в кандидатах; решение владельца по четырём остаточным
native-рискам DEP-01 [зафиксировано](risk-acceptance.md).
[Итоговая приёмка #25](../operations-stage-5/README.md) отдельно согласована и
выполнена на неизменном комплекте. Затем все семь PR отдельно согласованы и
[слиты в main](../operations-main-integration/README.md). Релиз/registry и замена
default deployment не выполнялись; сами images не пересобирались.
