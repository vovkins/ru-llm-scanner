# Документация

Статус: спецификация и локальный механизм обнаружения готовы. Команды
snapshot/diff, JSON/HTML и baseline работают через CLI. Доступны подготовка/сборка Analyzer,
проверки адаптера и JSON Schema. Внутренний Git API читает снимки/сравнения
деревьев и готовит тексты. Scan API соединяет его с Analyzer/словарём,
сохраняет находки/координаты/охват и возвращает безопасную сводку.
Production Docker/Compose, offline transfer и пример Jenkins реализованы.
Сквозная приёмка и согласованная историческая репетиция обновления/отката
Analyzer выполнены; [итоговые результаты](../verification/stage-7/README.md).
Все семь этапов слиты в `main` после отдельного согласования;
[результаты интеграции](../verification/main-integration/README.md).
Релиз и публикация образов пока не выполнялись.

## Пользователю и оператору CI

| Задача | Документ |
| --- | --- |
| Понять назначение и готовность | [README](../README.md) |
| Выбрать снимок или переход и понять охват | [Режимы](scan-modes.md) |
| Запустить доступный CLI | [Dev quickstart](cli-quickstart.md) |
| Запустить готовые контейнеры | [Docker quickstart](docker-quickstart.md) |
| Собрать и перенести в закрытую среду | [Build и offline transfer](offline-build.md) |
| Разобрать сбой/восстановить cleanup | [Эксплуатация](operations.md) |
| Подключить доверенный CI | [Jenkins example](jenkins.md) |
| Задать аргументы и профиль проверки | [CLI и конфигурация](configuration.md) |
| Читать JSON/HTML и трактовать результат | [Отчёты](reports.md) |
| Переиспользовать предыдущую проверку | [Baseline](baseline.md) |
| Понять категории и ограничения детекторов | [Механизм прокси](upstream.md) |
| Собрать и проверить локальный Analyzer | [Подготовка и запуск проверок](analyzer.md) |
| Обновить закреплённый механизм | [Обновление Analyzer](updating-analyzer.md) |
| Использовать Git API и проверить допустимый клон | [Git reader](git-reader.md) |
| Выполнить внутренний snapshot/diff и offline-проверку | [Scan API](scan-api.md) |
| Работать с чувствительными отчётами | [Безопасность](../SECURITY.md) |

Штатный запуск проверен на CPU Linux ARM64 в Docker Desktop; реальный Jenkins,
GPU и Linux-host/другие платформы требуют отдельной проверки.

## Разработчику

- [Архитектура](architecture.md) и [принятые решения](decisions/README.md).
- [Требования и приёмочные сценарии](requirements.md).
- [Схема отчёта](../schemas/report-v1.schema.json) и [примеры](../examples/reports/README.md).
- [Разработка и проверки](development.md), [CONTRIBUTING](../CONTRIBUTING.md).
- [Результаты проверки Analyzer на этапе 2](../verification/stage-2/README.md).
- [Результаты проверки Git/text на этапе 3](../verification/stage-3/README.md).
- [Результаты scan pipeline и качества кода на этапе 4](../verification/stage-4/README.md).
- [Результаты CLI/отчётов/baseline на этапе 5](../verification/stage-5/README.md).
- [Результаты production Docker/transfer на этапе 6](../verification/stage-6/README.md).
- [Итоговая приёмка/upgrade/rollback на этапе 7](../verification/stage-7/README.md).
- [Последовательное слияние семи PR и проверка main](../verification/main-integration/README.md).
- [Ревью перед подготовкой к эксплуатации: замечания и матрица проверок](review/README.md).
- [Исправления RV-01–RV-05 и повторные проверки](../verification/operations-stage-2/README.md).
- [Лицензирование](licensing.md), [постоянные инструкции](../AGENTS.md).

Источником договорённостей служит [общая задача #1](https://github.com/vovkins/ru-llm-scanner/issues/1).
Каждый этап получает отдельную задачу и явное согласование до реализации.
Текущая спецификация подготовлена по [плану этапа 1](https://github.com/vovkins/ru-llm-scanner/issues/2).
Реализация [этапа 2](https://github.com/vovkins/ru-llm-scanner/issues/3)
согласована 2026-10-18 и завершена; проверки и ограничения описаны в руководстве
Analyzer. [Этап 3](https://github.com/vovkins/ru-llm-scanner/issues/5)
согласован 2026-10-19; Git API и классификация реализованы, результаты описаны
в отдельном руководстве. [Этап 4](https://github.com/vovkins/ru-llm-scanner/issues/7)
согласован 2026-10-19; scan API и отдельная оценка качества реализованы.
[Этап 5](https://github.com/vovkins/ru-llm-scanner/issues/9) согласован
2026-10-19: CLI, отчёты и baseline реализованы.
[Этап 6](https://github.com/vovkins/ru-llm-scanner/issues/11) согласован
2026-10-19: production Docker/Compose, offline transfer и пример Jenkins реализованы.
[Этап 7](https://github.com/vovkins/ru-llm-scanner/issues/13) согласован 2026-10-19;
сквозная приёмка и историческая репетиция реальных версий выполнены.
