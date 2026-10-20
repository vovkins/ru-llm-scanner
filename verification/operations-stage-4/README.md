# Проверки подготовки к эксплуатации — этап 4

План: [#22](https://github.com/vovkins/ru-llm-scanner/issues/22), явно согласован
2026-10-19. Проверяемый продукт и руководства: `755152b8d658506ddb3da819569270ca46f2ae57`
(PR #23 поверх #21/#19). Эта ветка добавляет проверочные инструменты и evidence;
runtime, detectors, corpus, default locks и зависимости не меняет.

Проверочный этап завершён, [draft PR #27](https://github.com/vovkins/ru-llm-scanner/pull/27).
Это завершение испытаний с открытыми проблемами, не допуск к эксплуатации.

**Итоговая приёмка требует решения новых RV-06/DEP-01/DEP-02.** Успех regression
наборов ниже не отменяет воспроизведённый отказ на реальном тексте и dependency
совпадения. Полный Requests с 300/900 s не завершён; результаты разных видов
проверки не объединяются в общий безусловный passed.

## Матрица и бюджеты

| Группа | Предусловия | Ожидание | Evidence и границы |
| --- | --- | --- | --- |
| Contracts/docs/unit | Python 3.12, dev requirements, pinned Analyzer context | 0, полный collector без skipped | JSON counts; HTTP stubs отдельно от модели |
| Git/upstream | trusted Linux test images, curated fixtures | 0; неизменный input | Host/Linux и 478 upstream tests без NER weights |
| Fresh build | отдельный `git archive 755152b`, отдельный venv; trusted proxy `da4f50a`, локальный base/cache | новый context→seal→runtime→wheel→deployment→parity→CLI→acceptance→export | Online только подготовка; build/runtime offline; использование cache явно |
| Ready package | новый минимальный install, отдельно launcher/docs, export из предыдущей строки | import/verify 0; snapshot 0; diff/strict/settings и ошибки 0/1/2 | Без host dev venv/src/proxy/context; тот же Docker store |
| Production/faults | явный новый deployment, только свои fixtures/projects | положительные и ожидаемые отрицательные сценарии; input unchanged/cleanup | Inspect/route, без внешних запросов; hard kill требует operator cleanup |
| Browser | локальный localhost server только с synthetic reports | фильтры, XSS/CSP, desktop/narrow, errors/coverage | UI checks/screenshots; реальные находки не открываются публично |
| Capacity | seed/состав фиксированы, 10/100/1000 малых файлов, отдельный длинный текст | измеренные exit/coverage/wall/CPU/memory/output/cleanup | concurrency 1/2; synthetic run budget 300 s; public повтор 900 s; не SLA |
| Public Requests | no-checkout clone v2.32.5, fixed SHA, без выполнения кода | полный snapshot, фактический exit/coverage | Полные reports private; aggregate counts без оценки precision/recall |
| Advisories | inventory фактических images, OSV и Debian Tracker | свежие ответы или явное unavailable | Только публичные names/versions; backports сравниваются dpkg; pins не меняются |
| Preservation | baseline IDs/hashes/StartedAt до тестов | прежний proxy/default locks/profile/corpus/чужие контейнеры сохранены | Не выполнять prune, daemon restart или остановку чужих проектов |

Стенд: macOS/Docker Desktop Linux ARM64, Docker 29.6.1, Compose 5.2.0,
VM 10 CPU и 8 321 515 520 bytes RAM; семь фоновых контейнеров.
Тесты с моделью последовательно, кроме явного concurrency/parallel acceptance.
Лимит Analyzer по умолчанию 3 GiB; аварийный OOM снижает память только своего
контейнера до 128 MiB. Ни один тест не перезапускает Docker daemon.

Полные логи/отчёты, package и runtime inventory находятся в игнорируемом
`.build/operations-validation/` с приватными outputs. Здесь сохранены
только проверенные безопасные сводки. Предыдущие verification JSON остаются
историческими свидетельствами и не переписываются результатами этого этапа.

Непроверенные среды: другой физический offline host, Linux AMD64/GPU,
корпоративный PKI и реальный Jenkins controller/Groovy/plugins. Локальная
последовательность Jenkins adapter→launcher→containers проверяется отдельно.

## Выполненные группы

| Evidence | Результат | Граница вывода |
| --- | --- | --- |
| [unit](unit-tests.json) | 144, failures/errors/skipped = 0 | Подготовлен pinned `.build/analyzer`; HTTP fixtures не NER |
| [upstream](upstream-tests.json) | 478 tests, 7 curated files | Отдельный test image без NER weights |
| [host Git](git-host.json), [Linux Git](git-linux.json) | по 41 | Linux non-root/network none; hostile config/objects/paths/strict text |
| [NER parity](offline-verification.json) | 77 raw/patched, 4 dictionary cases | Реальная закреплённая модель, Unicode/long tail, signature/hash failures |
| [code-v1](scan-verification.json) | 46 direct parity; TP 33 / FP 13 / FN 4 | Exact precision 71.74%, recall 89.19%; разметка/пороги сохранены |
| [installed code](installed-code.json) | 20 package files совпали с source; public/packaged schema совпали | Новый wheel/image, а не прежний default |
| [CLI](cli-verification.json) | 9 сценариев | Snapshot/diff/strict/profile/artifacts; дополнительные 46 code-v1 cases отдельно |
| [acceptance](acceptance-verification.json) | 16 сценариев | A=B/цепочка/merge/rename/delete/mode/history limit |
| [Compose](docker-verification.json) | 25 сценариев | Изоляция/permissions/signals/crash/timeout/parallel/cleanup |
| [faults](fault-verification.json) | настоящий OOMKilled и отмена после находки: exit 2 | Находка сохранена, owned cleanup выполнен; memory sample не peak |
| [SIGKILL](hard-kill-verification.json) | host -9, 2 orphan containers/1 network, operator cleanup | Не обещает exit 2 мёртвого launcher; daemon не перезапускался |
| [extras](extras-verification.json) | 14 сценариев | Private output 0700/0755/0777, transfer rejection, Jenkins adapter 0/1/2; не controller |
| [fresh steps](fresh-steps.json), [ready install](ready-walkthrough.json) | Оба маршрута пройдены | Новые каталоги, cache явно, один новый lock, Python `-I -S` у ready route |
| [browser](browser/browser-observations.json) | desktop 1280 / narrow 390; filters, XSS/Unicode/multiline, 0 console errors | Single IAB, synthetic only, DOM/CSP без packet capture |
| [advisories](dependency-advisories.json) | Свежие базы доступны; обнаружены DEP-01/DEP-02 | Это открытые риски, не passed security clearance; [подробно](dependencies.md) |

Documentation checker сам не открывает браузер и не устанавливает комплект;
его поля `*_performed=false` относятся к области этого инструмента. Реальные
walkthrough/browser evidence приведены отдельными строками. Counts contracts
и проверка сохранности приведены в [completion](completion.json),
[contracts](contracts-verification.json) и [preservation](preservation.json).

## Измеренная ёмкость

[Probe и повторяемый порядок](reproduce.md), [сводка](capacity-verification.json).
Измерено на фоне семи сохранённых контейнеров, без других собственных model runs
для семи synthetic случаев. Default limits: Analyzer 2 CPU/3 GiB, scanner 1 CPU/1 GiB.
Model startup, supervision и cgroup sampling входят в wall time.

| Случай | Текст bytes | Wall s | Exit / findings | Analyzer observed memory.peak MiB | Output bytes |
| --- | ---: | ---: | --- | ---: | ---: |
| 10 файлов | 230 | 6.179 | 1 / 1 | 568.54 | 27325 |
| 100 файлов, concurrency 1 | 2300 | 11.084 | 1 / 10 | 570.40 | 114831 |
| 100 файлов, concurrency 2 | 2300 | 10.939 | 1 / 10 | 569.15 | 114831 |
| 1000 файлов | 23000 | 65.295 | 1 / 100 | 573.52 | 989819 |
| Один длинный файл | 68817 | 54.698 | 0 / 0 | 896.48 | 18276 |
| Тот же файл, max-file-bytes 1024 | 68817 | 6.349 | 2 / 0, file_too_large | 566.77 | 18727 |
| 128 паролей в одном файле | 4736 | 12.462 | 1 / 128 | 671.31 | 263309 |

Первые четыре/длинный/many-findings имеют complete coverage, вход неизменён,
cleanup выполнен; превышение лимита остаётся incomplete. Изменение concurrency
на этом малом наборе почти не ускорило run, без повторных замеров статистический
вывод невозможен. Начальная настройка — concurrency 1 и штатные budgets, затем
замер на целевых данных. Один 68.8 KB файл обрабатывался дольше ста малых;
число файлов и порог 10 MiB не определяют время/безопасный максимум модели.

RAM — начисленная cgroup память при существующем shared page cache VM, не
универсальный минимальный объём RAM. CPU lifetime counters и sampled `/tmp`
bytes сохранены в JSON; финальный интервал может быть пропущен. Это не peak disk
measurement. Нагрузки, платформы и размеры за пределами этих случаев непроверены.

Первая попытка нового dev probe завершилась ошибкой повторного exclusive create
progress-файла после 100 файлов. Исправлена только запись прогресса harness;
все семь synthetic случаев повторены в новом output, предыдущие outputs/logs
сохранены приватно. Ошибка не относится к продуктовым reports.

## Публичные репозитории

[Requests v2.32.5](https://github.com/psf/requests/tree/v2.32.5):
commit `b25c87d7cb8d6a18a37fa12442b5f883f9e41741`,
tree `2663dda7dbb8ce123af703b4573d85d09383ba0f`, 132 файла / 5 190 867 blob bytes.
Первый полный snapshot с budget 300 s завершился за 301.510 s, **exit 2**:
54 analyzed / 9 unsupported / 69 error, 216 сохранённых находок.
Это неполный аудит. Manifest/errors/полные значения приватны; в сводке только
counts/hashes/categories. Unsupported: 8 image и 1 PDF; расширения не исключались.
Повтор всего Requests с budget 900 s завершился за **901.682 s, exit 2**:
68 analyzed / 11 unsupported / 53 error, 276 сохранённых находок.
[Evidence](public-requests-900.json). `AUTHORS.rst` снова дал analyzer_unavailable;
SVG 883 794 bytes достиг file analyze timeout 600 s. Ещё два analyzer_unavailable
наблюдались на `pyproject.toml` и `requirements-dev.txt` после SVG; их первопричина
отдельно не изолирована и не приписывается автоматически RV-06. Остальные 49
file errors — scan_interrupted при общем timeout, плюс глобальный scan_cancelled.
Unsupported: 10 raster image / 1 PDF. Никаких скрытых исключений/урезания файла.
Таким образом **полная проверка Requests не подтверждена** даже при большем budget.
Повторные попытки/увеличение лимитов без исправления RV-06 не создают clean baseline.

Дополнительно полностью проверен [Pallets ItsDangerous 2.2.0](https://github.com/pallets/itsdangerous/tree/2.2.0):
commit `096c8d42545d3b68ea21a4f890fb2b2d8979c0bd`,
tree `3ff0edaf2d039896397fe8d91d558935a038f823`, 60 файлов / 135 624 bytes.
**Exit 1, coverage complete**, 58 analyzed / 2 unsupported image / 0 error,
102 находки за 100.106 s. [Evidence](public-itsdangerous-verification.json).
Analyzer ограничен 2 GiB, scanner — 1 GiB; параллельно работал Requests900 и
семь исходных контейнеров, поэтому время не является изолированным benchmark.
Код ни одного клона не выполнялся, input неизменён, owned cleanup выполнен.

На реальном коде нет frozen ground truth. Категория/score не подтверждают
действительность credentials. Например, в первой частичной выдаче Requests
195 INTERNAL_IP являются IP literals (50 global / 145 non-global по ipaddress);
они встречаются в документации/примерах, не доказывают утечку. Правила/категории
прокси не изменялись ради реального репозитория.

## Открытые решения

RV-06 (P1): обычный `AUTHORS.rst` Requests (8037 bytes) изолированно даёт
exit 2 за 14.830 s, 0 analyzed / 1 error. Прямой HTTP probe в отдельном
network-none Analyzer подтверждает **503 / required_ner_unavailable / windowing /
window_boundary_unresolved** за 8.252 s. Это отдельный отказ обработки, не
следствие общего 300 s budget. [Snapshot evidence](authors-repro.json),
[bounded HTTP detail](authors-http.json),
[подробный отдельный план #26](https://github.com/vovkins/ru-llm-scanner/issues/26).
Scanner сохраняет fail-closed, но полный аудит/clean baseline такого состояния
невозможен до исправления. Первопричина boundary condition ещё не установлена.
Ни файл, ни категории не исключались ради прохождения.

DEP-01 (P1) / DEP-02 (P2): [разбор](dependencies.md) и отдельно согласуемый
[план #24](https://github.com/vovkins/ru-llm-scanner/issues/24).
План [этапа 5 #25](https://github.com/vovkins/ru-llm-scanner/issues/25) подготовлен;
итоговая приёмка не начата, нужны отдельное согласование и disposition RV-06/рисков.
Успех функциональных тестов не принимает dependency риски от имени владельца.

## Сохранность и итог

[67 protected files/hashes](preservation.json), исходный proxy `da4f50a` и его
tracked tree, main `336feb6`, прежние default/test images, модель/словарь/corpus/
default locks/профиль сохранены. Семь исходных контейнеров продолжают работать с
теми же Running/StartedAt; собственных Compose контейнеров/сетей не осталось.
Browser tab/localhost server закрыты. Private отчёты/логи/пакет оставлены локально
для разбора; GH содержит только безопасные metadata/counts/hashes и synthetic QA.
Merge/release/tags/registry/внешние настройки/лицензия не выполнялись.

Полные команды и ограничения измерений — [reproduce.md](reproduce.md).
Открытые результаты следует устранить или явно решить до [этапа 5 #25](https://github.com/vovkins/ru-llm-scanner/issues/25);
этапы исправлений #24/#26 и итоговая приёмка требуют отдельного согласования.
