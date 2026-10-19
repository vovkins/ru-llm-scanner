# Результаты проверок

Эти материалы фиксируют конкретные ревизии, images, fixtures, команды и среду.
Исторический passed не является результатом проверки любого последующего кода.
Полные чувствительные report.json/report.html и локальные assertion logs не
публикуются; открытые evidence содержат hashes/counts/синтетические метрики.

## Актуальный цикл подготовки к эксплуатации

| Работа | Материалы | Что подтверждено |
| --- | --- | --- |
| Ревью на `336feb6` | [Отчёт и карта рисков](../docs/review/README.md) | Статическое ревью, focused unit и воспроизведения; исходные JSON сохранены |
| Исправления RV-01–RV-05 | [operations-stage-2](operations-stage-2/README.md) | 144 unit без skipped, реальные parity/CLI/Compose/Jenkins adapter и private output |
| Документация по ролям | [operations-stage-3](operations-stage-3/README.md) | Сверка команд/путей/locks, валидные синтетические примеры, ссылки и неизменность runtime |
| Комплексные проверки #22 | [operations-stage-4](operations-stage-4/README.md) | Новый комплект, оба walkthrough, реальные модель/CLI/Compose/faults, browser, ёмкость, публичный snapshot и свежие advisories |
| RV-06 #26 | [operations-ner-windowing](operations-ner-windowing/README.md) | Ограниченное восстановление границ, полные входы, fail-closed, отмена и восстановление |
| DEP-01/DEP-02 #24 | [operations-dependencies](operations-dependencies/README.md) | Чистый offline closure, уникальный inventory, реальная parity/quality, полный Requests; native residuals требуют решения владельца |

Оба руководства пройдены в новых каталогах на том же Docker Desktop store.
Это не испытание другого физического offline host. Обнаруженные dependency
риски и смешанный packaging inventory исправлялись по согласованным #24/#26.
У нового кандидата inventory однозначен, 478 upstream/96 NER/155 host tests,
77 NER/4 dictionary и code-v1 33/13/4 сохранены. Полный Requests завершён:
119 analyzed/13 unsupported/0 errors, 612 кандидатов, exit 1, без дополнительных
excludes. Пять native advisory имеют явный статус `owner_review_required`;
DEP-01 не объявлен полностью устранённым. Итоговая приёмка
[#25](https://github.com/vovkins/ru-llm-scanner/issues/25) не начата.

## История первой реализации

| Набор | Содержание |
| --- | --- |
| [stage-2](stage-2/README.md) | Analyzer build/seal, upstream tests, real raw/patched NER/dictionary, зависимости/уведомления |
| [stage-3](stage-3/README.md) | Изолированное чтение Git/text, SHA-1/SHA-256, hostile metadata, bytes/encoding/limits |
| [stage-4](stage-4/README.md) | Pipeline, code-v1 direct parity и независимая оценка качества |
| [stage-5](stage-5/README.md) | Установленный CLI, JSON/HTML, schema/semantic validation, baseline/HTML QA |
| [stage-6](stage-6/README.md) | Production Compose isolation/lifecycle, permissions/Jenkins adapter, offline transfer |
| [stage-7](stage-7/README.md) | Сквозная приёмка и настоящая историческая репетиция обновления/отката |
| [main-integration](main-integration/README.md) | Семь merge-коммитов и повторные проверки слитого main |

Номер первоначального этапа не равен номеру этапа нового эксплуатационного цикла.
Итоги не переписываются после переноса документации: старые doc paths сохраняют
переходы на канонические страницы.

## Как читать результаты

| Вид проверки | Что доказывает | Чего не доказывает |
| --- | --- | --- |
| Schema/examples/links | Структура, ограниченные инварианты синтетических примеров, целостность документации | Реальный Git, модель, runtime isolation |
| Unit с HTTP stub | Контракт клиента/pipeline/ошибок и собственные регрессии | Качество настоящей NER |
| Raw/patched parity | Сохранение результатов закреплённого механизма после API-адаптации | Полноту обнаружения любых данных |
| Direct code parity | Совпадение pipeline с прямым Analyzer+словарём на code-v1 | Отсутствие FP/FN относительно независимой разметки |
| Independent quality | TP/FP/FN на заданном frozen corpus | Гарантию качества на произвольном клоне |
| Production/CLI acceptance | Реальные синтетические сценарии с конкретными images/платформой | Поддержку непроверенного сервера/CI/PKI |
| Documentation review | Согласованность описания с кодом/артефактами и проверку примеров | Самостоятельное прохождение свежей установки |

TEST-01: часть CLI/dictionary unit требует prepared `.build/analyzer`.
Отсутствующие assets приводят к skipped; такой запуск не считается полным.
[Как подготовить и разделить группы](../docs/development.md).

## Среда и известные ограничения

Подтверждено: CPU Linux ARM64 в Docker Desktop на Apple Silicon, Docker 29.6.1,
Compose 5.2.0; host Python 3.12.14, исторические images Python 3.11.16,
новый кандидат #24 — Python 3.11.17. Другие версии требуют
проверки совместимости в целевой среде. AMD64/GPU, реальный Linux-host UID/ACL,
настоящий Jenkins controller, корпоративный PKI и другой физический offline host
не проверены. Локальная adapter-последовательность не равна испытанию Jenkins.

Code-v1 содержит 46 файлов и 37 размеченных мест: **TP 33 / FP 13 / FN 4**, exact
precision **71.74%**, recall **89.19%**. 46/46 direct parity сохраняется отдельно.
Модель/пороги/разметка не ретюнились ради метрик. Ёмкость arbitrary repository,
общая транзакция JSON/HTML и жёсткий wall deadline CPU join не обещаются.

За решениями о лицензии, канале vulnerability reports, целевом сервере и Jenkins
обращайтесь к владельцу. [Текущий план](https://github.com/vovkins/ru-llm-scanner/issues/16).
