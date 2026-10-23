# Документация ru-llm-scanner

Основной маршрут текущих исходников: **make build → make test → make scan → HTML/JSON**.
Новые команды ещё не входят в опубликованный v0.2.0. Для него и ручных процедур
сохранён [расширенный маршрут](admin/advanced.md); старые evidence относятся
к своим source/images, а не к будущему выпуску.

| Задача | Начать здесь |
| --- | --- |
| Получить первый отчёт, проверить commit или A/B | [Пользователь](user/README.md) |
| Подготовить хост, собрать и сопровождать установку | [Администратор](admin/README.md) |
| Подключить доверенный CLI в CI | [Jenkins](admin/jenkins.md) |
| Найти точные флаги/defaults/форматы | [Справочник](reference/README.md) |
| Изменить код и выбрать нужные проверки | [Разработчик](development.md) |

## Пользователю

[Пошаговая инструкция](user/README.md): HEAD и конкретный commit, автоматические
приватные каталоги, optional OUTPUT/CONFIG, коды 0/1/2, HTML/JSON, diff и strict baseline.
Для scan используются подготовленные локальные images; ручные venv/модель/locks не нужны.

## Администратору

[Среда и ресурсы](admin/README.md) → [единая сборка и повторный запуск](admin/build.md)
→ [диагностика и хранение](admin/operations.md).
[CPU и исторические измерения](admin/linux-amd64.md),
[обновление Analyzer](admin/updating-analyzer.md), [Jenkins](admin/jenkins.md).
Ручная сборка/export/import, explicit launcher и релизные комплекты —
[отдельный раздел](admin/advanced.md).

## Справочник

[Команды/параметры](reference/simple-workflow.md), [повседневные проверки](reference/everyday-tests.md),
[режимы/охват](reference/scan-modes.md), [конфигурация](reference/configuration.md),
[runtime](reference/runtime.md), [отчёты](reference/reports.md),
[baseline](reference/baseline.md), [каталог распознавания](reference/detection.md),
[артефакты](reference/artifacts.md), [ошибки](reference/errors.md).

[JSON Schema](../schemas/report-v1.schema.json) ·
[defaults config](../examples/config/scanner.json) ·
[синтетический HTML](../examples/demo/report.html) ·
[контрактные JSON](../examples/reports/README.md). Примеры не пригодны как baseline.

## Разработчику

[Разработка](development.md), [архитектура](architecture.md), [ADR](decisions/README.md),
[требования](requirements.md), [Git reader](git-reader.md), [Scan API](scan-api.md),
[Analyzer](analyzer.md), [внутренний Python CLI](cli-quickstart.md).
[Корпус](../tests/corpus/README.md), [ревью](review/README.md),
[verification](../verification/README.md), [CONTRIBUTING](../CONTRIBUTING.md),
[SECURITY](../SECURITY.md), [лицензирование](licensing.md), [AGENTS](../AGENTS.md).

Текущий цикл — [#38](https://github.com/vovkins/ru-llm-scanner/issues/38).
Каждый этап получает отдельный согласованный план; документация не разрешает
слияния, обновление proxy или публикацию. Первоначальные проверки сохранены в
verification; [About](about.md) — подготовленный текст metadata.
