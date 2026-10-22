# Упрощение: этап 2 — build, scan и diff

Основание: согласованный [план #40](https://github.com/vovkins/ru-llm-scanner/issues/40),
общий [#38](https://github.com/vovkins/ru-llm-scanner/issues/38).
Draft [PR #42](https://github.com/vovkins/ru-llm-scanner/pull/42) зависит от
спецификации [PR #41](https://github.com/vovkins/ru-llm-scanner/pull/41), source
`2ec86e11df8bd17b1666b842d3067ba22339ffe2`. Оба остаются без слияния.

## Что реализовано

`make build` автоматически выбирает профиль по Docker server, создаёт закреплённое
build-окружение, получает exact upstream/materials и связывает существующие
prepare/verify/build/seal/engine/wheel/deployment шаги. После проверки и короткого
synthetic smoke атомарно выбирается комплект для этого daemon/platform.
Повторный build проверяет и переиспользует исправный комплект.

`make scan REPO=...` по умолчанию проверяет HEAD, `make diff REPO=... FROM=... TO=...`
сохраняет прежнюю семантику конечных состояний и явного strict baseline.
Отчёты создаются приватно вне входного клона. Прямой `./scanner scan|diff`
сохраняет точные 0/1/2; Make при ошибке рецепта возвращает собственный код.
`make test` пока намеренно возвращает 2/test_suite_pending: suite относится к этапу 3.

Реализация: [entry](../../scanner), [Makefile](../../Makefile),
[dispatcher](../../scripts/workflow.py), [build](../../scripts/workflow_build.py),
[state](../../scripts/workflow_state.py). Low-level helpers и core pipeline
переиспользованы, не переписаны. [Контракт](../../docs/reference/simple-workflow.md).

## Проверки и применимость

Итоговый native run [39744041536](https://github.com/vovkins/ru-llm-scanner/actions/runs/39744041536)
на source `baee3230cefca525ee434e9af5e83402bf8f064c` прошёл на AMD64 и ARM64.
[AMD64 receipt](native-amd64.json), [ARM64 receipt](native-arm64.json),
[CI gates](native-run.json), [97 material inputs](material-inputs.json) относятся
к одной исходной точке. После неё менялись только docs/evidence и буквальный
quote/metacharacter subcase теста; runtime/build inputs совпадают.

На каждой архитектуре13 Make/CLI cases, concurrent scan/build reuse, injected
pre-assembly rollback, actual SIGTERM/cleanup; runtime acquisition commands0.
Полное synthetic значение сохранено в private JSON, console его не содержит.
Timeout отправил настоящий SIGINT и вернул2/run_timeout на обеих платформах.
Время всего build+контролей: AMD64 290.574s, ARM64 249.627s; это не benchmark
сканирования произвольного репозитория.23 observations Compose isolation на каждом
стенде. JSON/HTML/модели/сырые logs в публичные artifacts не включены.

Локально [215 unit/0skip](unit-check.json), включая29 focused, прошли на Python3.12.14
с доступом loopback. Первая sandbox-попытка с9 bind errors не считается pass.
[Contracts/format/Make](static-checks.json), [documentation checker](documentation-check.json)
и [focused review](review.md) отделены от model proof.
[История запусков](attempt-history.json) сохраняет первоначальные успешные runs
и отказ overly strict timeout gate39743057999 (AMD64 failure/ARM64 success).
В том gate проверялось единственное имя ошибки; final контроль наблюдает SIGINT,
code2, известные fail-closed diagnostics и cleanup. Конкретные коды сохраняются
в receipt. Неуспешный gate не объявлен пройденным.

Native harness [check_simple_workflow.py](../../scripts/check_simple_workflow.py)
собирает образы настоящим `make build`. Make/direct CLI и legacy launcher используют
одни образы и Git fixture. Сравниваются engine/configuration/coverage/result/findings,
без volatile report/run metadata. Проверяются HEAD и явный commit, clean baseline,
strict diff, invalid baseline/ref, auto/explicit output, отсутствие значения-canary
в console,0700/0600, неизменность dirty input clone. Docker guard запрещает acquisition
при scan и повторном build; проверяет internal network/non-root/read-only/logging none.
Timeout и SIGTERM выполняются на настоящем public scan; own cleanup проверяется отдельно.

Одновременный scan/build проверяет **повторное использование** текущего комплекта.
Сериализация builds, immutable selection и атомарное продвижение проверяются focused
тестами. Native rollback case намеренно инъецирует отказ **до assembly**: он не является
полным прерванным model rebuild. Эти границы сохраняются и в JSON receipts.

## Карта SW-01…SW-23

| Контракт | Реализация / свидетельство этапа 2 | Граница |
| --- | --- | --- |
| SW-01 | EntryTests: help/version/make default без daemon/model | Настоящие subprocess Make/CLI |
| SW-02–03 | Builder + daemon; обе native платформы; DaemonTests aliases/unsupported | Чистые disposable CI hosts; не целевой сервер владельца |
| SW-04 | Повторный native make build с Docker acquisition guard | Не обещание отсутствия сетевого доступа при первичной сборке |
| SW-05 | Existing upstream/offline corruption tests; publish failure/current unchanged; реальный build-child SIGTERM; native injected rollback | Полная аварийная пересборка не заявлена |
| SW-06 | flock subprocess, immutable selected path после promotion; concurrent real scan/reuse | Полная live смена нового engine относится к обновлению |
| SW-07 | StateTests: absent/stale/foreign/missing-image/symlink/corrupt; bounded private JSON | Malformed regular current восстанавливается новой checked сборкой; небезопасные ссылки не перезаписываются |
| SW-08–10 | Actual HEAD/commit/strict diff/baseline/ref и legacy parity; существующие Git/pipeline/baseline unit | Новая Requests/upstream/Jenkins приёмка не подменяется старой |
| SW-11–12 | OutputTests + actual auto/explicit0700/0600 | Нет chmod/overwrite чужих существующих outputs |
| SW-13–14 | Actual Make transport, Unicode/spaces, hostile assignments, ambient vars ignored; actual Make/CLI effective profile | GNU3.81 локально и Linux Make в CI |
| SW-15–16 | Actual direct0/1/2 и Make codes; strict parsing/config validation; infrastructure dominance test | Raw HTTPS не добавлен |
| SW-17 | Native timeout/SIGTERM; child cancellation; wrapper error dominance для Analyzer/cleanup/scanner faults | Полная новая OOM/fault matrix — следующий suite/приёмка |
| SW-18–19 | Own lifecycle reuse, native acquisition guard/isolation observations/input unchanged; preservation.json | Полный parallel-scan/fault suite — этап3 |
| SW-20 | Existing real Git security unit; isolated Python/Make marker tests; console canary guard | Чужой код не запускается |
| SW-21 | Явный test_suite_pending2, без false success | Suite — этап3, не выполнен здесь |
| SW-22 | Минимальные работающие инструкции/статусы обновлены | Полная переработка и walkthrough — этап4 |
| SW-23 | Direct CLI точные0/1/2 | Настоящий новый Jenkins pilot — этап6 |

## Сохранность и ограничения

[preservation.json](preservation.json):45 защищённых inputs сохранены, включая
src/locks/patches/dependencies/notices. Соседний proxy HEAD прежний;97 pinned files,
4 patches/модель/словарь/thresholds не обновлялись.7 чужих контейнеров и69 уникальных прежних
локальных image IDs (71 исходная запись) сохранены; v0.1.0/v0.2.0 metadata/assets не менялись.
Raw Docker inspect/env сохранены только в private `.build` и сюда не включены.

В CI используются read-only contents permissions. Registry/release jobs пропущены,
новых tags/push/OCI indexes/релизов и изменений production Jenkins нет.
Прежние принятые certifi/native-риски не исправлялись. Runtime images тестового
runner не обещаны доступными после job. Stage3 suite, полный Requests и перенос
нового proxy ещё не выполнялись; их исторические evidence не выдаются за новые.

## Следующий этап

Подробный [план этапа3 #43](https://github.com/vovkins/ru-llm-scanner/issues/43)
содержит24 чекбокса для повседневного `make test`. Он ждёт отдельного явного
согласования; реализация suite не начата. PR #41/#42 остаются открытыми draft.
