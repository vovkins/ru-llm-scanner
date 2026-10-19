# Синтетические примеры отчётов

Все JSON здесь — `artifact_kind=contract_example`, а не результаты запусков.
Commit/tree/image SHA, подписи и score иллюстративные; действующих credentials
нет. Поля модели и upstream ссылаются на исследованные версии, но не подтверждают
существование собранного образа scanner. Эти файлы нельзя использовать как baseline.

| Пример | Контрактный сценарий |
| --- | --- |
| [snapshot-clean](snapshot-clean.json) | Полный снимок без находок |
| [snapshot-findings](snapshot-findings.json) | Два места одного значения, Unicode и CRLF |
| [snapshot-empty](snapshot-empty.json) | Пустое дерево и нулевой охват текста |
| [snapshot-unsupported](snapshot-unsupported.json) | Явно неподдерживаемый объект |
| [diff-baseline-clean](diff-baseline-clean.json) | Условно проверенный A→B с наследованием |
| [diff-chain-clean](diff-chain-clean.json) | Следующий шаг B→C |
| [diff-no-baseline-clean](diff-no-baseline-clean.json) | Неизменённый файл `unverified` |
| [diff-identical-no-baseline](diff-identical-no-baseline.json) | A=B без baseline не подтверждает весь снимок |
| [incomplete](incomplete.json) | Timeout выбранного файла, код 2 |
| [baseline-incompatible](baseline-incompatible.json) | Профиль не совпал, требуется snapshot |
| [preflight-error](preflight-error.json) | Коммит недоступен, engine/manifest ещё неизвестны |

[Исходные тексты и индекс](../report-fixtures.json) нужны только проверке
координат и хешей примеров. Это не корпус качества детекторов и не настоящий
Git-репозиторий. Цепочка примеров показывает контракт отчётов; реальный
baseline обязан иметь `artifact_kind=scan_report` и доверенное происхождение.

Проверка: [руководство разработчика](../../docs/development.md).
