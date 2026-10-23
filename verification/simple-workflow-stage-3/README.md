# Упрощение: этап 3 — повседневный make test

Согласованный [план #43](https://github.com/vovkins/ru-llm-scanner/issues/43),
общий [#38](https://github.com/vovkins/ru-llm-scanner/issues/38).
Draft [PR #44](https://github.com/vovkins/ru-llm-scanner/pull/44) зависит от #41/#42;
все остаются без слияния. Собственные изменения этапа — после8dfa134.

`make build` сам готовит проверенный venv и отдельный historical source-only
unit fixture. `make test` выполняет tools/unit/contracts/documentation/format/runtime
и возвращает0 только после всех обязательных групп. Отказ, skip, отсутствие группы
или отмена —2. Test ничего не устанавливает/не скачивает и не подготавливает
непроверенную установку автоматически. [Полный контракт](../../docs/reference/everyday-tests.md).

Реализация: [suite](../../scripts/workflow_test.py),
[environment](../../scripts/workflow_environment.py), [support](../../scripts/workflow_support.py),
[unit gate](../../scripts/run_workflow_units.py),
[native acceptance](../../scripts/check_workflow_test.py).
Переиспользованы existing prepare_unit_assets/upstream verification и legacy runtime;
core pipeline/Git/report/detection не переписывались.

## Статус проверок

Локальный [новый venv + отдельный unit fixture](local-unit-check.json):225 тестов,
0skip/0errors/0failures/0missing required modules на sourcefa10c5e.
39 focused, включая10 новых integrity/result tests, прошли также с MAKELEVEL=1.
Это unit/stub proof; реальная модель подтверждается отдельным native receipt.
[Focused review](review.md), [история запусков](attempt-history.json).

Итоговый [native run39764343216](https://github.com/vovkins/ru-llm-scanner/actions/runs/39764343216)
на source `fa10c5e6fd261b9a431f7281d5b253ddffd0d4cb` — SUCCESS обеих CPU.
[AMD64](native-amd64.json), [ARM64](native-arm64.json), [CI gates](native-run.json),
[102 material inputs](material-inputs.json). После этого source менялись только
документация/evidence; все102 build hashes совпадают. Fast CI39764351277 прошёл.

На каждой CPU выполнены8 outer CLI cases плюс отмена suite в runtime-фазе:
make build, make test, missing installation/support, corrupt assets/environment,
explicit build repair без image rebuild, повторный direct test, SIGTERM2/cleanup.
В каждом успешном suite225 unit/0skip/0missing,6 групп passed, реальные snapshot/
HEAD/strict diff/baseline/Make CONFIG/resources,2 parallel scan,timeout/SIGTERM,
private reports/input unchanged и0 acquisition commands во время test.
Ожидаемые scanner1/2 не превратили успешные synthetic cases в отказ всего suite.

[Измерения](resources.json):4CPU на обоих стендах; Docker15.61GiB AMD64,
15.57GiB ARM64. Первый suite78.050s/79.419s, повтор75.975s/77.609s соответственно.
Весь acceptance с build/repair/двумя suite/cancel —388.916s/347.993s.
Это ресурсы опорного стенда и время этих synthetic cases, не минимальные
требования или обещание производительности. Peak container RSS не измерялся.

Первый native39762846405 и fast39763355152 не приняты и сохранены в history:
build обеих CPU прошёл, но unit error fixtures зависели от GNU Make diagnostics
и Docker context/API. Исправления не меняли core или expected success suite.

Native harness выполняет настоящий build, make test, missing installation/support,
corrupt unit assets/environment, explicit build repair без image rebuild и повторный
direct test. Отдельно отправляет SIGTERM suite во время runtime и проверяет code2,
cancelled summary и cleanup собственных project IDs. Docker guard запрещает
acquisition после первичной сборки; repair может получать Python/source материалы
только внутри явного make build. Raw logs/reports/model/cache не загружаются.

## Границы

Исторический unit fixture имеет собственную identity; это не ARM64 inference
на AMD64. Каждый запуск использует свою проверенную копию. Runtime cases работают
с actual sealed images native платформы. Полная release/Requests/upstream/quality/
Jenkins матрица не заменена коротким suite и не объявлена заново пройденной.

Наибольшая одновременная нагрузка runtime — два Analyzer+Scanner. Limits остаются
3g/1g на каждый pipeline; сумма8g — сумма лимитов, не измеренный peak и не reservation.
Измеренное время групп записано по native receipts. Целевой сервер владельца
не выбран; его capacity/Jenkins pilot остаётся отдельной проверкой.

Сохраняются опубликованные v0.1.0/v0.2.0, прежние locks/dependencies/model/dictionary,
proxy и чужие ресурсы. Релиз, tags, images/registry write и merge не выполняются.
Полная переработка role guides и clean first-run walkthrough — следующий этап4,
который требует отдельного явного согласования.

Подробный [план этапа4 #45](https://github.com/vovkins/ru-llm-scanner/issues/45)
содержит24 pending чекбокса. Реализация не начата.

## Сохранность

[preservation.json](preservation.json):45 защищённых inputs/core/locks/dependencies,
proxy HEAD,7 чужих контейнеров и69 прежних unique local image IDs сохранены;
v0.1.0/v0.2.0 identities/assets не менялись. Raw Docker inspect/env в Git не включены.
