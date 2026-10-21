# ru-llm-scanner

Локальный сканер чувствительных данных в Git-репозиториях. Проверяет снимок
указанного коммита или переход между двумя состояниями и сохраняет самостоятельный
HTML и JSON с категориями, координатами, полными значениями и контекстом.

Механизм распознавания закреплён за версией
[ru-llm-proxy](https://github.com/vovkins/ru-llm-proxy): NER, структурные правила,
распознаватели credentials и отдельный словарь бизнес-терминов. Сборка может
использовать сеть для подготовки; **анализ готовыми образами работает локально**,
без интернета и внешних LLM/API.

## Начать работу

| Ваша задача | Маршрут |
| --- | --- |
| Просканировать локальный клон в готовом окружении | [Руководство пользователя](docs/user/README.md) |
| Подготовить образы, установить и передать окружение | [Руководство администратора](docs/admin/README.md) |
| Найти параметры, форматы и правила baseline | [Справочник](docs/reference/README.md) |
| Изменить проект или выполнить dev-проверки | [Разработка](docs/development.md) |

После получения launcher и готовых локальных images от администратора:

```sh
cd /opt/ru-llm-scanner
python3 scripts/docker_scanner.py verify \
  --deployment-lock /srv/ru-llm-scanner/deployment.json
python3 scripts/docker_scanner.py snapshot \
  --deployment-lock /srv/ru-llm-scanner/deployment.json \
  --repo /data/project --commit HEAD --output /data/scanner-results/initial
```

Это пример путей: `/data/scanner-results` должен существовать, `initial` — быть
новым либо пустым приватным каталогом оператора вне клона. Нужны host Python 3.11+,
Docker/Compose и non-root доступ к daemon; venv/исходный proxy пользователю не нужны.
Сам по себе checkout scanner без подготовки images к запуску не готов.
[Полные предусловия и последовательность](docs/user/README.md).

Версия **v0.2.0** предусматривает отдельные offline-комплекты для **Linux AMD64
и ARM64**. Выбирайте архив по архитектуре Docker server:
[GitHub Releases](https://github.com/vovkins/ru-llm-scanner/releases),
[получение, проверка и offline-установка](docs/admin/releases.md).
Два публичных GHCR packages — `ghcr.io/vovkins/ru-llm-scanner` и
`ghcr.io/vovkins/ru-llm-scanner-analyzer`; общий тег `0.2.0` объединяет обе
архитектуры, платформенные теги — `0.2.0-amd64` и `0.2.0-arm64`.
Доступность конкретного выпуска проверяйте в GitHub Releases.

[Серверная инструкция и ресурсы](docs/admin/linux-amd64.md),
[протоколы нативной приёмки](verification/linux-amd64/README.md),
[подготовка и результаты v0.2.0](verification/release-v0.2.0/README.md).
Прежний **v0.1.0** и GHCR `:0.1.0` сохраняют исходные ARM64 images и hashes;
[архивная инструкция](docs/admin/releases-v0.1.0.md). Слияние исходников или pull
не заменяют установленный комплект и его deployment.

## Возможности

| Режим | Что проверяется |
| --- | --- |
| `snapshot --commit B` | Все поддерживаемые текстовые файлы состояния B |
| `diff --from A --to B` | Полное содержимое новых, изменённых и переименованных файлов B |
| `diff --baseline ... --require-baseline` | Изменённые файлы B плюс подтверждение неизменённых из совместимого доверенного clean-отчёта A |

Читаются **tracked Git-объекты коммита**, а не текущие файлы рабочей папки.
Staged/untracked/незакоммиченные изменения не входят в результат. Scanner не
делает checkout/fetch, не запускает код, хуки или фильтры проверяемого проекта.

Каталог включает персональные данные, документы/реквизиты РФ, инфраструктурные
адреса, пароли, ключи, токены и словарные термины.
[Полный каталог и источники](docs/reference/detection.md).
Версии upstream/модели/патчей и image IDs закрепляются явно; обновление переносит
механизм через ограниченный адаптер без переписывания Git/pipeline/report слоёв.

## Результат

Откройте [синтетический HTML-пример](examples/demo/report.html) или
[соответствующий JSON](examples/demo/report.json). Он иллюстрирует формат,
не является результатом реального клиента и не подходит как baseline.

Находка содержит категорию, файл, коммит состояния, строки/столбцы, полное
значение, контекст, источник, score и доступный rule ID. HTML работает локально
с поиском/фильтрами без CDN; JSON предназначен для автоматической обработки.
**Отчёты содержат чувствительные данные полностью.** Храните их приватно;
в console launcher выводится только безопасная техническая сводка.

| Код | Значение |
| --- | --- |
| `0` | Заданная проверка завершена без находок |
| `1` | Заданная проверка завершена с находками |
| `2` | Ошибка или неполнота, в том числе при наличии находок |

Смотрите coverage и assurance: clean diff без baseline относится только к
изменённым файлам. Существование одного JSON/надписи clean не заменяет успешный
код всего запуска и доверенное происхождение. [Правила отчётов](docs/reference/reports.md).

## Границы и статус

Опубликованный **v0.1.0** содержит CPU Linux ARM64. Поддержка AMD64 включена
в `main`: полный нативный прогон [#33](https://github.com/vovkins/ru-llm-scanner/issues/33)
успешен на обеих архитектурах, [слияние и контроль main](verification/linux-amd64/main-integration/README.md)
проверены отдельно. Конкретные versioned images получают отдельную
[приёмку выпуска](verification/release-v0.2.0/README.md).

| Комплект | Проверенная платформа | Состояние |
| --- | --- | --- |
| v0.1.0 | Linux ARM64, Docker Desktop на Apple Silicon | Опубликован, прежние images/locks сохранены |
| Новый `cpu-linux-amd64` | Native Ubuntu 24.04 x86-64, EPYC 7763/AVX2, Docker 29.6.1 / Compose 2.38.2 | Build, offline import, модель, production/faults и настоящий Jenkins проверены; полный финальный прогон успешен |
| Новый `cpu-linux-arm64` | Native Ubuntu 24.04 ARM64 | Регрессия тех же runtime/build путей и модели пройдена |
| GPU, rootless/userns-remap, другие ОС/CPU/корпоративные ACL | В эту приёмку не входят | Нужна отдельная проверка |

[Серверная установка и ресурсы](docs/admin/linux-amd64.md) ·
[Доверенный Jenkins pipeline](docs/admin/jenkins.md) ·
[Протоколы AMD64/ARM64](verification/linux-amd64/README.md).
Полный Requests на обеих архитектурах: **119 analyzed / 13 unsupported / 0 errors**,
612 кандидатов, код 1. Решения/координаты/источники совпали с принятым ARM64
reference; абсолютная разница confidence укладывается в `1e-5`. Действительность
найденных значений во внешних сервисах не проверялась.

Владелец [принял четыре остаточных native-риска](verification/operations-dependencies/risk-acceptance.md)
для закрытого контура; библиотеки этим не исправлены. По
[certifi #34](verification/linux-amd64/certifi-advisory.md) владелец 2026-10-21
выбрал сохранение версий для штатного offline Docker-маршрута. Произвольный
HTTPS endpoint raw CLI не входит в принятую конфигурацию и требует отдельной
оценки CA policy и зависимостей. Для каждого комплекта нужен явный deployment;
исторический default сохранён. Смена runtime/profile требует нового полного
clean snapshot для baseline. [История предыдущей приёмки](verification/operations-main-integration/README.md).

Diff сравнивает конечные A/B и **не сканирует промежуточную историю**. Секрет,
добавленный и удалённый между ними, может остаться в Git. PDF/Office/OCR,
растровые изображения, архивы, содержимое LFS/подмодулей и незакоммиченные файлы вне области.
SVG/XML могут анализироваться как текст по правилам `text-v1`; визуального анализа нет.
Исключения/неподдерживаемые объекты/ошибки видны в манифесте.

Нулевой результат не гарантирует абсолютную полноту распознавания. На независимом
синтетическом code-v1: **TP 33 / FP 13 / FN 4**, exact precision **71.74%**,
recall **89.19%**. Техническая parity на 46/46 файлах — отдельная проверка;
известные пропуски и ошибки категорий сохранены в [результатах](verification/operations-stage-2/README.md).

## Сопровождение

[Карта документации](docs/README.md) · [CONTRIBUTING](CONTRIBUTING.md) ·
[Безопасность](SECURITY.md) · [Архитектура](docs/architecture.md) ·
[Обновление Analyzer](docs/admin/updating-analyzer.md) ·
[План подготовки к эксплуатации](https://github.com/vovkins/ru-llm-scanner/issues/16)

Лицензия scanner — [MIT](LICENSE). [Происхождение и лицензии компонентов](docs/licensing.md),
[сторонние уведомления](THIRD_PARTY_NOTICES.md). Не публикуйте действующие секреты
или полные отчёты в Issues; приватный канал сообщения согласуется с владельцем.
