# Упрощение: этап 1 — спецификация

Основание: согласованные [общий план #38](https://github.com/vovkins/ru-llm-scanner/issues/38)
и [этап #39](https://github.com/vovkins/ru-llm-scanner/issues/39).
Исходный checkpoint — `37e5e0e7dfd545941a6de008585e226b9271e5a0` (v0.2.0),
ветка `codex/simple-workflow-spec`. Результат этапа —
[спецификация](../../docs/reference/simple-workflow.md) и
[ADR-0007](../../docs/decisions/0007-simple-workflow.md).
Новый Makefile/CLI ещё не реализованы; сценарии ниже — задания для будущей приёмки.
Это не новая native/runtime/model проверка и не изменение релиза.

## Карта существующего маршрута

Код и документы сверялись по tracked-файлам, без чтения config/secrets/tmp
соседнего proxy. Его текущий рабочий HEAD не становится источником новой сборки.
`upstream.lock.json` сохраняет закреплённый da4f50a,97 файлов и4 патча.

| Текущий ручной шаг | Существующий компонент | Будущий исполнитель |
| --- | --- | --- |
| Установить системные Python/Git/Make/Docker/Compose и дать non-root доступ | [Предпосылки](../../docs/admin/README.md) | Оператор; build/scan проверяют и объясняют отказ |
| Создать dev venv и выбрать версии инструментов | [Build §1](../../docs/admin/build.md) | build создаёт своё закреплённое окружение |
| Выбрать CPU профиль и десяток промежуточных путей | [Профили](../../upstream.lock.json), [candidate build](../../scripts/check_cpu_candidate.py) | build по Docker server, с уникальным внутренним build root |
| Экспортировать точную ревизию и применить patches | [upstream.prepare/verify_context](../../src/ru_llm_scanner/upstream.py), [analyzer entry](../../scripts/analyzer.py) | build; не обновление upstream |
| Получить модель, wheels, DEBs и составить context | [prepare_offline_analyzer](../../scripts/prepare_offline_analyzer.py), artifact locks | build с проверенным cache и явным доступом в сеть |
| Собрать/проверить Analyzer и сохранить реальные IDs | [upstream.build/seal](../../src/ru_llm_scanner/upstream.py) | build, затем synthetic smoke |
| Экспортировать engine и выбрать wheel | [prepare_scan_engine](../../scripts/prepare_scan_engine.py), pip wheel | build, точная package version и единственный проверенный wheel |
| Собрать Scanner и связать deployment | [build_scanner](../../scripts/build_scanner.py) | build в отдельном новом каталоге |
| Выбрать deployment и выполнить verify | [load_lock/verify](../../scripts/docker_scanner.py) | build перед продвижением и scan перед запуском |
| Создать private output, вручную задать refs/config/baseline | [launcher](../../scripts/docker_scanner.py), [configuration](../../src/ru_llm_scanner/configuration.py) | scan/diff; пользователь задаёт REPO и нужные refs/расширения |
| Запустить Compose, наблюдать состояние, убрать свои ресурсы | [run_scan/cleanup](../../scripts/docker_scanner.py) | Тот же launcher, без новой реализации lifecycle |
| Интерпретировать JSON/HTML, принять clean baseline | [Отчёты](../../docs/reference/reports.md), [baseline](../../docs/reference/baseline.md) | Пользователь/доверенный CI; baseline не продвигается автоматически |
| Полный native suite, Jenkins, Requests, public release delivery | [v0.2.0 evidence](../release-v0.2.0/README.md), workflows | CI/сопровождающий; не обязательный повтор при каждой локальной сборке |

`check_cpu_candidate.py` полезен как карта последовательности, но его CLI
ориентирован на disposable native runner, принудительный no-cache и приёмку.
В новом build повторно используются его низкоуровневые шаги; сам весь harness
не становится пользовательской сборкой. Детекторы, Git, baseline, report schema
и renderer не требуют новой реализации.

## Наблюдаемые проблемы текущих документов

- Нет Makefile; DEFAULT_LOCK launcher указывает на исторический ARM64 deployment.
- Пример wheel в admin/build указывал0.1.0 при package0.2.0; исправлен как фактическая ошибка текущего ручного пути.
- Карта документации указывала0.1.0 и завершённый цикл #16 как текущие; исправлены версия и навигация.
- Архитектурный обзор/требования сохраняли раннюю фразу о непроверенном настоящем Jenkins; ссылка на фактическую v0.2.0 приёмку уточняет статус. Исторические JSON evidence не переписываются.
- Поэтапное описание ручных locks сохраняется до реализации нового пути; новые make-примеры имеют явный статус проектируемых.

## Матрица будущей приёмки

Все строки ниже **не выполнены на этапе1**. Показанный этап — основной владелец
сценария, а не готовый результат; испытания записываются отдельными receipts.

| ID | Сценарий и ожидаемый результат | Этап |
| --- | --- | --- |
| SW-01 | help/version/пустая цель make без сети, Docker и модели; нет side effects | 2 |
| SW-02 | Чистое поддерживаемое окружение: build с интернетом → scan REPO, без JSON/ручного wheel; приватные JSON/HTML | 2,4 |
| SW-03 | Native Linux AMD64/ARM64 и aliases; профиль выбран по Docker server; другая/неподдерживаемая платформа отклонена | 2,4 |
| SW-04 | Повторный build: проверенный кеш/успешный комплект используется, pins не плавают, ненужный no-cache не навязан | 2 |
| SW-05 | Повреждённый artifact/context, неуспешный seal/smoke или отмена build: нет продвижения, предыдущая установка сохранена | 2 |
| SW-06 | Параллельные builds одного daemon сериализованы; scan удерживает один комплект при переключении current | 2,3 |
| SW-07 | Установка отсутствует/stale, images удалены, daemon другой, state подменён ссылкой: отказ до scan, понятное действие | 2,3 |
| SW-08 | HEAD и явный commit: tracked state, dirty input clone не меняется, untracked/staged содержимое не анализируется | 2,3 |
| SW-09 | Diff FROM/TO анализирует полные изменённые файлы, координаты/coverage/assurance прежние; нет аудита промежуточной истории | 2,3 |
| SW-10 | Совместимый clean baseline со strict; missing/forged/wrong-profile baseline даёт2, не silent changed-only; авто-продвижения нет | 2,3 |
| SW-11 | Default output уникален, вне input,0700/0600; OUTPUT пустой/новый private; existing/nonempty/symlink/input overlap не перезаписаны | 2,3 |
| SW-12 | Недоступен HOME/XDG root либо он внутри input: явная ошибка и возможность безопасного OUTPUT, без скрытого fallback | 2,3 |
| SW-13 | Пути с пробелами/Unicode; literal argv; hostile make/shell значения не исполняются, безопасный отказ для неразрешённых случаев | 2,3 |
| SW-14 | Make/CLI имеют одинаковый effective profile; внешний REPO/CONFIG и .env входного клона не подменяют параметры | 2,3 |
| SW-15 | Прямой scan/diff возвращает0/1/2; код make не используется как scanner code; ошибка инфраструктуры побеждает clean report | 2,3 |
| SW-16 | Ресурсы/таймауты и CONFIG доступны явно, прежние defaults/валидация сохранены; raw HTTPS route не добавлен | 2,3 |
| SW-17 | SIGINT/SIGTERM, run timeout, Analyzer exit/OOM и ошибка cleanup: корректный отказ, сохранение доступных private reports и только own cleanup | 2,3 |
| SW-18 | Параллельные scan не делят Compose project/output; чужие контейнеры/образы не удаляются | 2,3 |
| SW-19 | Scan без pull/build/fetch/внешних API и downloads; внутренний Analyzer/read-only mounts/non-root/logging none сохранены | 2,3 |
| SW-20 | Git hooks/config/filters и найденные значения не исполняются/не попадают в console; output не прикидывается clean при ошибке | 2,3 |
| SW-21 | make test даёт определённый suite/проверенный результат; обязательные пропуски/отсутствие assets не объявляются success | 3 |
| SW-22 | README и руководства пройдены с чистого состояния, версии/параметры совпадают; новых JSON-редактирований или offline целей не требуется | 4 |
| SW-23 | Реальный Jenkins вызывает trusted direct CLI, различает0/1/2, хранит reports приватно и не берёт executable/baseline из input workspace | 6 |

Полная матрица не помещается в default make test: этап3 выделяет нужный
повседневный suite, остальные проверки остаются в CI/отдельной приёмке.

## Проверки собственно этапа 1

Проверяются согласованность спецификации с исходниками, defaults и направлением
перевода scan→snapshot, documentation/contracts/local links/shell syntax,
реальное различие кодов локального GNU Make3.81 и неизменность существующих
runtime/build/locks/test inputs. Docker/модель/новые make-команды не запускаются.

[Сверка существующих flags/defaults](compatibility-check.json),
[результат documentation checker](documentation-check.json),
[контракты](contracts-check.json), [Make exit-status probe](make-exit-status.json),
[неизменность исходников и состав](source-preservation.json) относятся только
к этому этапу. До появления соответствующего файла проверка не считается выполненной.

## Следующий этап

Подробный план автоматизации build/scan/diff оформлен в
[задаче #40](https://github.com/vovkins/ru-llm-scanner/issues/40). Он ожидает
отдельного явного согласования; создание задачи не запускает реализацию.
