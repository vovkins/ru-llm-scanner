# Dependencies: результаты и отдельный план исправлений

Это исторический отчёт этапа #22. Планы #24/#26 впоследствии явно согласованы; ход исправлений, новый inventory и остаточные риски — [operations-dependencies](../operations-dependencies/README.md). Прежние результаты ниже сохранены для сравнения.

Проверка 2026-10-19 UTC относится к двум images из `runtime-verification.json`.
[Inventory и безопасные ответы](dependency-advisories.json) содержат названия,
версии, image IDs, per-record modified, время получения, response SHA-256 и
Last-Modified/ETag. Scanner runtime при этом не обращался к advisory-сервисам.
Отдельный инструмент отправлял только публичные PyPI package names/versions.

Источники: [OSV querybatch](https://google.github.io/osv.dev/post-v1-querybatch/),
[OSV API](https://osv.dev/docs/),
[Debian Tracker JSON](https://security-tracker.debian.org/tracker/data/json).
Это текущие ответы сервисов, без единого номера выпуска всей базы.

## DEP-01 — P1: перед итоговой приёмкой нужен допуск зависимостей

93 уникальные пары PyPI name/version дали 45 package/advisory records,
**23 группы после объединения aliases**, включая GHSA/PYSEC одной CVE.
Это version matches; доказательства эксплуатации в scanner нет.

| Компонент | Измеренный состав | Применимость по коду/среде; следующий шаг |
| --- | --- | --- |
| Transformers | 4.57.6, только Analyzer; 6 групп | Advisory затрагивают Trainer, X-CLIP conversion, LightGlue loading, custom generation/save paths. Runtime загружает закреплённый локальный BERT token classifier с `trust_remote_code=False`; эти другие пути не вызываются штатным scan. Требуется отдельная проверка обновления/совместимости, это не устранение уязвимых версий |
| Starlette | 0.46.2, только Analyzer; 7 групп | Изолированный Linux JSON API, без пользовательских multipart/forms/FileResponse/StaticFiles/HTTPEndpoint. UNC Windows и file-serving условия не соответствуют штатному маршруту. Host/path issues требуют отдельного разбора ASGI/FastAPI, включая автоматически доступные docs. Не считать весь компонент неприменимым |
| urllib3 | 2.7.0, только Analyzer; 3 группы | Штатный scanner→Analyzer transport — httpx, внешней сети нет; advisory о TLS proxy и обработке внешних HTTP responses актуальны прежде всего для online-подготовки/других способов применения. Проверить dependency closure и обновить отдельно |
| pip | scanner module 24.0; Analyzer module 26.2.1 при старом dist-info; 6 групп | pip не запускается при scan; затронуты установка, архивы, entry points/index URLs. Сборочный риск сохраняется, нужен чистый комплект и повторный inventory |
| setuptools | metadata/`__version__` 79.0.1; Analyzer также содержит dist-info 84.0.0; 1 группа | Advisory про sdist/Unicode normalization на macOS; runtime Linux. Не выдавать это за полную проверку build-host пути; разобрать смешанную установку |

Примеры первичных сообщений:
[Starlette FileResponse](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8),
[Starlette forms](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq),
[Transformers LightGlue fix](https://github.com/huggingface/transformers/commit/676559d5022b74aaa0cee1cee0842b7f27c5320e),
[urllib3 proxy TLS](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77),
[setuptools](https://github.com/pypa/setuptools/security/advisories/GHSA-h35f-9h28-mq5c).
Fixed events в JSON — сведения источника для отдельных advisory, а не готовый
совместимый набор рекомендуемых pins. Для части записей fixed event отсутствует.

Debian trixie: 83 source/version пары, 1714 записей с релизным статусом;
**1529 отсеяны `dpkg --compare-versions`** как installed ≥ fixed.
Остались 185 потенциальных source/version/advisory записей (181 уникальный ID),
из них 42 с известной более новой fixed version; 56 помечены `unimportant`,
129 — `not yet assigned`. Open/undetermined/unimportant не равны подтверждённой
эксплуатации. `resolved` в базе не означает, что старый локальный пакет обновлён.

Есть более новые distro fixes для glibc, gzip, xz-utils, PCRE2, sqlite3,
OpenSSL и Perl. Пример — [PCRE2 CVE-2026-103111](https://security-tracker.debian.org/tracker/CVE-2026-103111).
Условия включают controlled regex/JIT, SQLite FTS, QUIC/DTLS/crypto либо Perl
архивы; многие не входят в штатное чтение Git. Полная достижимость всех native
путей не доказана. Проверка учитывает backports, а не сравнение с upstream semver.

Python 3.11.16/OpenSSL 3.5.7 инвентаризированы. Скопированный CPython официального
python image не представлен Debian python package и не покрывается PyPI query;
для него нужен отдельный vendor audit. Проверка не является полной SBOM или
сертификатом отсутствия уязвимостей.

## DEP-02 — P2: неоднозначный inventory packaging в Analyzer

В одном site-packages есть `pip-24.0.dist-info` и `pip-26.2.1.dist-info`,
`setuptools-79.0.1.dist-info` и `setuptools-84.0.0.dist-info`.
`metadata.version('pip')` выбирает 24.0, фактический `pip.__version__` — 26.2.1.
Для setuptools metadata и `__version__` показывают 79.0.1 при двух dist-info;
проверки всего содержимого модуля не было. Поэтому шесть совпадений старого pip
нельзя без оговорки приписывать выполняемому pip Analyzer; у scanner pip 24.0
подтверждён. Provenance/сканирование зависимости должны различать остаточные
metadata и фактические модули. На распознавание в выполненных тестах это не повлияло.

## Предлагаемый отдельный объём, до допуска этапа 5

- Согласовать DEP-01/DEP-02 и критерии допуска; сохранить текущие images/locks.
- Разобрать все 23 PyPI alias groups и Debian candidates по достижимости,
  добавить CPython/vendor audit, указать исправление либо обоснованное решение владельца.
- Установить причину смешанных dist-info и подготовить чистый кандидат build
  без редактирования работающего образа; выбрать согласованные base/dependency
  pins и полный closure с hashes/notices.
- Собрать кандидаты отдельно, проверить inventory, offline isolation, 478 upstream,
  77 NER/4 dictionary parity, code-v1 46 direct parity и независимые 33/13/4,
  CLI/Compose/Jenkins/private-output, smoke transfer и update/rollback.
- При drift распознавания или необходимости менять модель/пороги/словарь
  остановить принятие кандидата и представить отдельное решение; разметку не менять.
- Обновить инструкции/provenance/baseline compatibility и остаточные риски;
  представить отдельный draft PR. Default deployment, merge/release/registry
  не изменять без дополнительного решения.

Здесь зафиксирован план, его реализация не начата. Завершение проверочного
этапа 4 не означает автоматического принятия обнаруженных dependency рисков.
