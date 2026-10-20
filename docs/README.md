# Документация ru-llm-scanner

Начните с маршрута своей роли. Текущая версия `0.1.0.dev0`, images подготавливаются
администратором и анализируют локально; release/registry-комплект не опубликован.
[Выполненные проверки и границы стендов](../verification/README.md).

| Роль | Основной маршрут |
| --- | --- |
| Пользователь | [Готовность → snapshot → HTML/JSON → diff/baseline](user/README.md) |
| Администратор | [Среда → импорт или build → verify → handoff → сопровождение](admin/README.md) |
| Разработчик | [Окружение, устройство репозитория и группы проверок](development.md) |

## Пользователю

[Руководство](user/README.md) последовательно объясняет подготовленный Git-вход,
выбор коммита, private output, коды 0/1/2, чтение отчёта, совместимый baseline,
настройки и действия при ошибках. Для запуска готовых images не нужны исходный
proxy, venv или build context.

## Администратору

- [Среда, компоненты и чеклист передачи](admin/README.md).
- [Готовый offline-пакет: import/verify/контрольный snapshot](admin/installation.md).
- [Fresh build: один runtime lock через все стадии](admin/build.md).
- [Эксплуатация, диагностика и cleanup](admin/operations.md).
- [Обновление и откат механизма](admin/updating-analyzer.md).
- [Jenkins: trusted pipeline и приватные artifacts](admin/jenkins.md).

## Справочник

[Карта справочника](reference/README.md): [режимы/охват](reference/scan-modes.md),
[CLI и конфигурация](reference/configuration.md), [Docker runtime/budgets](reference/runtime.md),
[JSON/HTML](reference/reports.md), [baseline](reference/baseline.md),
[каталог и качество](reference/detection.md), [артефакты/locks](reference/artifacts.md),
[ошибки](reference/errors.md).

[JSON Schema](../schemas/report-v1.schema.json) ·
[конфигурация по умолчанию](../examples/config/scanner.json) ·
[синтетический HTML](../examples/demo/report.html) ·
[контрактные JSON-примеры](../examples/reports/README.md).

## Разработчику и сопровождающему

- [Архитектура](architecture.md), [ADR](decisions/README.md), [требования](requirements.md).
- [Git reader](git-reader.md), [Scan API](scan-api.md), [Analyzer API и dev-проверки](analyzer.md).
- [Dev Python CLI](cli-quickstart.md) — установка и engine assets для разработки;
  пользовательский Docker маршрут описан отдельно.
- [Тестовые группы и prepared assets](development.md), [независимый корпус](../tests/corpus/README.md).
- [Результаты проверок](../verification/README.md), [ревью](review/README.md),
  [исправления](../verification/operations-stage-2/README.md).
- [Участие](../CONTRIBUTING.md), [безопасность](../SECURITY.md),
  [лицензирование](licensing.md), [постоянные инструкции](../AGENTS.md).
- [Подготовленный текст About](about.md) — внешние metadata не применены.

История первоначальных семи этапов доступна через verification и
[исходный план](https://github.com/vovkins/ru-llm-scanner/issues/1).
Текущий цикл — [#16](https://github.com/vovkins/ru-llm-scanner/issues/16),
документация — [#20](https://github.com/vovkins/ru-llm-scanner/issues/20).
Каждый следующий этап требует отдельного явного согласования.
