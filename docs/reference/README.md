# Справочник

Пошаговый запуск — в [руководстве пользователя](../user/README.md),
подготовка/обслуживание — в [руководстве администратора](../admin/README.md).
Здесь находятся канонические правила, на которые ссылаются оба маршрута.

| Тема | Документ |
| --- | --- |
| Make/CLI build, scan, diff, test: параметры и defaults | [Простой интерфейс](simple-workflow.md) |
| Повседневный suite: предпосылки, группы и диагностика | [Make test](everyday-tests.md) |
| Snapshot/diff, Git-состояния, text-v1 и coverage | [Режимы и охват](scan-modes.md) |
| Анализ/scope/execution/presentation, CLI и defaults | [Конфигурация](configuration.md) |
| Host launcher, container budgets, private output и lifecycle | [Docker runtime](runtime.md) |
| Схема, поля, координаты/value/context, exit/assurance | [JSON/HTML](reports.md) |
| Допуск, совместимость и цепочка A→B | [Baseline](baseline.md) |
| Категории, источники, модель/словарь и известное качество | [Распознавание](detection.md) |
| Source/runtime/deployment, images и provenance | [Артефакты](artifacts.md) |
| Сравнение proxy и отдельный source-only candidate | [Управляемое обновление](upstream-update.md) |
| Типовые ошибки и действия | [Ошибки](errors.md) |

[JSON Schema](../../schemas/report-v1.schema.json) и
[контрактные JSON-примеры](../../examples/reports/README.md) — источники формата.
[Конфигурация по умолчанию](../../examples/config/scanner.json) и
[HTML-демонстрация](../../examples/demo/report.html) синтетические.
Пример документации не допускается как baseline.

Внутренние API и build details — в [руководстве разработчика](../development.md),
ограничения стендов и фактические прогоны — в [verification](../../verification/README.md).

[Простой make/CLI интерфейс](simple-workflow.md) реализован для build/scan/diff
по #40, [suite make test](everyday-tests.md) — по #43. Эти команды поставляются в v0.3.0; в v0.2.0 их нет.
