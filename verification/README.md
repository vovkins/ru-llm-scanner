# Результаты проверок

[Упрощение, этап5: controlled proxy update](simple-workflow-stage-5/README.md) — whole-tree25 changes/106 source candidate, exact review/patches, native AMD64/ARM64 source preparation +244unit/0skip/current-engine regression. Новый engine пока не принят.

[Упрощение, этап4: docs и clean native first run](simple-workflow-stage-4/README.md) —19cases/9docblocks/225unit без skips на AMD64/ARM64. Browser попытка заблокирована URL policy; browser pass не заявлен.

Эти материалы фиксируют конкретные ревизии, images, fixtures, команды и среду.
Исторический passed не является результатом проверки любого последующего кода.
Полные чувствительные report.json/report.html и локальные assertion logs не
публикуются; открытые evidence содержат hashes/counts/синтетические метрики.

## Упрощение сборки и запуска

[Спецификация этапа1](simple-workflow-stage-1/README.md) и
[реализация этапа2](simple-workflow-stage-2/README.md) относятся к циклу #38.
Build/scan/diff реализованы в отдельном PR;
[повседневный make test этапа3](simple-workflow-stage-3/README.md) проверен
на AMD64/ARM64. Полная новая документация и перенос обновления proxy относятся
к следующим этапам.
Опубликованные выпуски ниже сохранены.

## v0.2.0: опубликованная AMD64/ARM64 поставка

[Приёмка и публикация](release-v0.2.0/README.md): 186 unit на каждой архитектуре,
upstream/parity/quality/production, 13 Jenkins AMD64 сценариев, полный Requests;
полные скачанные архивы, анонимный GHCR tag/index/child pull и installed control
успешны на обеих native платформах.

## Linux AMD64 и нативная ARM64 регрессия

Исторический этап #33 до version bump: поддержка включена через PR #35.
Новые versioned images проверены отдельно в [v0.2.0](release-v0.2.0/README.md).
[План #33 и нативные протоколы](linux-amd64/README.md),
[слияние и новые unit/control main](linux-amd64/main-integration/README.md).
Нативные Ubuntu 24.04 AMD64/ARM64 сборки, parity/quality, полный Requests,
production/fault проверки и отдельная установка с пустым Docker/containerd store
подтверждены. Настоящий Jenkins AMD64 прошёл 13 завершённых сценариев. Итоговый
полный повтор с измерением ресурсов успешен; опубликованный v0.1.0 остаётся ARM64.

## Актуальный цикл подготовки к эксплуатации

Первый выпуск v0.1.0: [финальные проверки и публикация](release-v0.1.0/README.md).
161 unit без skipped, реальные parity/CLI/acceptance, offline import и отдельный
ARM64 GitHub runner, анонимный pull обоих GHCR images. Исторические наборы ниже
сохраняют собственные ревизии и границы.

| Работа | Материалы | Что подтверждено |
| --- | --- | --- |
| Ревью на `336feb6` | [Отчёт и карта рисков](../docs/review/README.md) | Статическое ревью, focused unit и воспроизведения; исходные JSON сохранены |
| Исправления RV-01–RV-05 | [operations-stage-2](operations-stage-2/README.md) | 144 unit без skipped, реальные parity/CLI/Compose/Jenkins adapter и private output |
| Документация по ролям | [operations-stage-3](operations-stage-3/README.md) | Сверка команд/путей/locks, валидные синтетические примеры, ссылки и неизменность runtime |
| Комплексные проверки #22 | [operations-stage-4](operations-stage-4/README.md) | Новый комплект, оба walkthrough, реальные модель/CLI/Compose/faults, browser, ёмкость, публичный snapshot и свежие advisories |
| RV-06 #26 | [operations-ner-windowing](operations-ner-windowing/README.md) | Ограниченное восстановление границ, полные входы, fail-closed, отмена и восстановление |
| DEP-01/DEP-02 #24 | [operations-dependencies](operations-dependencies/README.md) | Чистый offline closure, уникальный inventory, реальная parity/quality, полный Requests; остаточные native-риски приняты владельцем для закрытого контура |
| Итоговая приёмка #25 | [operations-stage-5](operations-stage-5/README.md) | Точный состав стека/комплекта, применимость предыдущих результатов, новый installed verify/snapshot/strict diff/negative baseline, матрица готовности |
| Интеграция цикла #16 в main | [operations-main-integration](operations-main-integration/README.md) | Семь merge-коммитов, точное равенство принятому дереву, новый full unit и installed control на слитом main |

Оба руководства пройдены в новых каталогах на том же Docker Desktop store.
Это не испытание другого физического offline host. Обнаруженные dependency
риски и смешанный packaging inventory исправлялись по согласованным #24/#26.
У нового кандидата inventory однозначен, 478 upstream/96 NER/155 host tests,
77 NER/4 dictionary и code-v1 33/13/4 сохранены. Полный Requests завершён:
119 analyzed/13 unsupported/0 errors, 612 кандидатов, exit 1, без дополнительных
excludes. Риски четырёх native advisory [приняты владельцем 2026-10-20](operations-dependencies/risk-acceptance.md)
для закрытого контура; это решение по DEP-01, исправление этих библиотек не заявлено. Итоговая приёмка
[#25](https://github.com/vovkins/ru-llm-scanner/issues/25) выполнена в отдельном
кандидате: [заключение для локального пилота](operations-stage-5/README.md).
Предыдущие полные прогоны не объявлены новыми: их входы/hashes/images повторно
сверены. Все семь PR затем отдельно согласованы и слиты:
[проверка итогового main](operations-main-integration/README.md).
Исторический default deployment и прежние images сохранены.

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
корпоративный PKI и другой физический offline host не проверялись этим
историческим набором. Новые AMD64/ARM64 Linux-host и настоящие Jenkins результаты
отделены в [#33](linux-amd64/README.md); локальная adapter-последовательность
из старого набора сама по себе не равна испытанию Jenkins.

Code-v1 содержит 46 файлов и 37 размеченных мест: **TP 33 / FP 13 / FN 4**, exact
precision **71.74%**, recall **89.19%**. 46/46 direct parity сохраняется отдельно.
Модель/пороги/разметка не ретюнились ради метрик. Ёмкость arbitrary repository,
общая транзакция JSON/HTML и жёсткий wall deadline CPU join не обещаются.

За решениями о лицензии, канале vulnerability reports, целевом сервере и Jenkins
обращайтесь к владельцу. [Текущий план](https://github.com/vovkins/ru-llm-scanner/issues/16).
