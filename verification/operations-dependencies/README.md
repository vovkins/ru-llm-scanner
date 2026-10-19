# DEP-01/DEP-02: чистый закреплённый комплект

План [#24](https://github.com/vovkins/ru-llm-scanner/issues/24) согласован
2026-10-19. Ветка построена поверх [RV-06](../operations-ner-windowing/README.md).
Это результаты отдельного кандидата; полный Requests, повторные acceptance и
walkthrough ещё выполняются. Прежние images/default deployment/main сохранены.
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
55 `unimportant`, 84 `not yet assigned`. Они не объявлены исправленными.
Для каждого описаны API/предпосылка, supported workflow и источник; source match
не доказывает запуск уязвимого инструмента или исчерпывающую достижимость.

Пять записей оставлены владельцу: libstdc++ `CVE-2026-102010`, `CVE-2026-95619`,
glibc `CVE-2026-19542`, zlib `CVE-2026-27171`, `CVE-2026-85091`. Размеры модели
ограничены, Git читает локальные objects, но полное исключение этих native paths
не доказано. Решение о риске не принято. Нерешённые P1 не закрываются автоматически;
итоговая приёмка #25 не начинается.

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

[155 host tests](unit-tests.json) прошли без skips. Первый запуск внутри sandbox не мог bind loopback HTTP fixtures; после выполнения с разрешённым локальным loopback прошёл весь набор. Пропусками эту проверку не заменяли. [Проверка документации](documentation.json) не подменяет runtime acceptance. Остальные эксплуатационные gates и полный Requests выполняются последовательно; их результаты добавляются после завершения.
