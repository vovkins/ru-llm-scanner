# Справочник

Пошаговый запуск — в [руководстве пользователя](../user/README.md),
подготовка/обслуживание — в [руководстве администратора](../admin/README.md).
Здесь находятся канонические правила, на которые ссылаются оба маршрута.

| Тема | Документ |
| --- | --- |
| Snapshot/diff, Git-состояния, text-v1 и coverage | [Режимы и охват](scan-modes.md) |
| Анализ/scope/execution/presentation, CLI и defaults | [Конфигурация](configuration.md) |
| Host launcher, container budgets, private output и lifecycle | [Docker runtime](runtime.md) |
| Схема, поля, координаты/value/context, exit/assurance | [JSON/HTML](reports.md) |
| Допуск, совместимость и цепочка A→B | [Baseline](baseline.md) |
| Категории, источники, модель/словарь и известное качество | [Распознавание](detection.md) |
| Source/runtime/deployment, images и provenance | [Артефакты](artifacts.md) |
| Типовые ошибки и действия | [Ошибки](errors.md) |

[JSON Schema](../../schemas/report-v1.schema.json) и
[контрактные JSON-примеры](../../examples/reports/README.md) — источники формата.
[Конфигурация по умолчанию](../../examples/config/scanner.json) и
[HTML-демонстрация](../../examples/demo/report.html) синтетические.
Пример документации не допускается как baseline.

Внутренние API и build details — в [руководстве разработчика](../development.md),
ограничения стендов и фактические прогоны — в [verification](../../verification/README.md).

[Проектируемый простой интерфейс](simple-workflow.md) — спецификация #39,
не инструкция к действующему runtime.
