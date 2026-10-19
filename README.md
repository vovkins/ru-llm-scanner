# ru-llm-scanner

Локальный сканер чувствительных данных в Git-репозиториях. Проект использует
механизм распознавания из [ru-llm-proxy](https://github.com/vovkins/ru-llm-proxy)
и предназначен для первоначального аудита и последующих проверок в CI.

## Статус

Первая предрелизная версия `0.1.0.dev0` находится в `main`. Доступны CLI
`snapshot/diff`, JSON/HTML с координатами и контекстом, проверяемая цепочка
baseline и явный учёт охвата/ошибок. Анализ использует закреплённый Analyzer
из `ru-llm-proxy` и отдельный словарный слой; Git-объекты читаются изолированно.
Штатный offline Docker/Compose launcher запускает анализ локально. Доступны
сборка и перенос готовых образов, пример Jenkins.
[Docker quickstart](docs/docker-quickstart.md),
[сборка и перенос](docs/offline-build.md), [Jenkins](docs/jenkins.md).
Сквозная приёмка первой версии и историческое обновление/откат Analyzer
пройдены в заявленных границах CPU ARM64. Семь PR слиты последовательно
после отдельного согласования; [проверка итогового main](verification/main-integration/README.md).
Релиз и образы не опубликованы.

Для проверки уже доступного механизма см. [руководство Analyzer](docs/analyzer.md).
Проверенная платформа — CPU `linux/arm64`. GPU-цели upstream сохранены, но
сборка и вывод на GPU на этом стенде не проверены.
[Результаты проверок и артефакты этапа 2](verification/stage-2/README.md).
[Git API и ограничения входа](docs/git-reader.md),
[результаты этапа 3](verification/stage-3/README.md).
[Scan API и воспроизводимый offline-прогон](docs/scan-api.md),
[результаты этапа 4](verification/stage-4/README.md).
[Проверки CLI/отчётов/baseline](verification/stage-5/README.md).
[Проверки production Docker и offline transfer](verification/stage-6/README.md).
[Итоговая приёмка и обновление/откат](verification/stage-7/README.md).

На отдельном синтетическом корпусе кода получены exact precision 71.74% и
recall 89.19% (37 размеченных мест). Ограничения текущей модели, включая
пропущенный телефон и ошибки категорий, сохранены в результатах этапа 4.
Соответствие pipeline прямому Analyzer+словарю проверено на 46/46 файлах;
это отдельная проверка, которая не означает безошибочное распознавание.

[Общий план и прогресс](https://github.com/vovkins/ru-llm-scanner/issues/1) ·
[Этап 1](https://github.com/vovkins/ru-llm-scanner/issues/2) ·
[Этап 2](https://github.com/vovkins/ru-llm-scanner/issues/3) ·
[Этап 3](https://github.com/vovkins/ru-llm-scanner/issues/5) ·
[Этап 4](https://github.com/vovkins/ru-llm-scanner/issues/7) ·
[Этап 5](https://github.com/vovkins/ru-llm-scanner/issues/9) ·
[Этап 6](https://github.com/vovkins/ru-llm-scanner/issues/11) ·
[Этап 7](https://github.com/vovkins/ru-llm-scanner/issues/13) ·
[Документация](docs/README.md)

## Сценарии первой версии

| Сценарий | Команда | Область проверки |
| --- | --- | --- |
| Первый аудит | `snapshot` | Поддерживаемые текстовые файлы указанного коммита |
| Проверка нового состояния | `diff` | Полное содержимое добавленных, изменённых и переименованных файлов в B |
| Последовательная проверка в CI | `diff --baseline ... --require-baseline` | Изменённые файлы B и подтверждённый охват неизменённых файлов из A |

```bash
# Из каталога scanner, с готовыми локальными образами и доверенным lock.
python3 scripts/docker_scanner.py snapshot \
  --repo /data/project --commit HEAD --output /data/results/initial

python3 scripts/docker_scanner.py diff \
  --repo /data/project --from COMMIT_A --to COMMIT_B \
  --baseline /data/results/initial/report.json --require-baseline \
  --output /data/results/check-B
```

Набор данных соответствует закреплённому механизму прокси: персональные данные,
документы и реквизиты РФ, инфраструктурные адреса, пароли, ключи, токены и
словарные бизнес-термины. [Каталог и ограничения](docs/upstream.md).

Launcher запускает два контейнера `scanner` и `analyzer` во внутренней сети
Docker. Репозиторий монтируется только для чтения, отчёты — отдельно для записи.
После подготовки образов анализ не требует интернета или внешних API.

## Результаты и границы

Результаты: самостоятельный HTML и версионированный JSON. Находка содержит
категорию, файл, коммит состояния, координаты, полное значение, контекст,
источник и score. **Отчёты содержат чувствительные значения полностью**;
в консоль по умолчанию выводится сводка.

`diff` сравнивает два конечных состояния и не проверяет промежуточную историю.
Секрет, добавленный и удалённый между A и B, может остаться в Git-истории.
Без совместимого доверенного baseline результат относится к проверенным
изменённым файлам. Изменение детекторов или области требует нового `snapshot`.

Первая версия ограничена содержимым текстовых файлов Git-дерева. PDF, Office,
изображения, архивы, содержимое LFS и подмодулей, незакоммиченные файлы и аудит
истории не входят в неё. Все исключения и ошибки должны отражаться в охвате.
Нулевой результат не гарантирует абсолютную полноту обнаружения.

| Код команды | Значение |
| --- | --- |
| `0` | Проверка завершена, в проверенной области нет находок |
| `1` | Проверка завершена, есть находки |
| `2` | Ошибка или неполная проверка, в том числе при наличии находок |

## Работа с проектом

- [Режимы и охват](docs/scan-modes.md), [CLI и настройки](docs/configuration.md).
- [Доступный Python API](docs/scan-api.md), [независимый корпус](tests/corpus/README.md).
- [Отчёты](docs/reports.md), [baseline](docs/baseline.md), [архитектура](docs/architecture.md).
- [Проверка спецификаций](docs/development.md), [участие](CONTRIBUTING.md), [безопасность](SECURITY.md).
- [Происхождение компонентов и статус лицензии](docs/licensing.md).

[Docker/Compose](docs/docker-quickstart.md), [диагностика](docs/operations.md),
[Jenkins example](docs/jenkins.md), [dev CLI и отчёты](docs/cli-quickstart.md).
[Сборка и offline-проверка Analyzer](docs/analyzer.md) уже доступны.
Лицензия самого проекта пока не выбрана.
