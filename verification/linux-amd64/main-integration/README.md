# Слияние Linux AMD64 и итоговая проверка main

Пользователь 2026-10-21 явно согласовал слияние PR #35, итоговую проверку,
обновление документации и #33. Релиз и публикация образов не разрешены.
[PR #35](https://github.com/vovkins/ru-llm-scanner/pull/35) слит merge-коммитом
`dd4a11fb91c3c6657fb28564dfe769b6ac4b6abf`; исходная ветка сохранена.

## Состав main

Первый родитель merge — прежний main `9c062c8684cb1c7d907cbb08fc1a2f3fd4c33ca5`,
второй — точный согласованный head `56fe5dd713ee3673736639895a4a34841b0d795f`.
Деревья merge и head полностью совпали:
`e0630fc7c6ae59f290661a6267f6aa855c6ffcb0`.
[Проверка слияния и применимости](merge-verification.json) содержит SHA и ссылки CI.
После merge изменялись только документация и безопасные протоколы.

Все 82 записанных runtime/build inputs совпадают с финальными receipts
[AMD64](../candidate/amd64/build-summary.json) и [ARM64](../candidate/arm64/build-summary.json).
Полный [native run39513865393](https://github.com/vovkins/ru-llm-scanner/actions/runs/39513865393)
успешен на source `4c0d5dc5e01b2e98708e628eb49f97d5c4678760` для обеих архитектур
и compare. [Fast CI согласованного head](https://github.com/vovkins/ru-llm-scanner/actions/runs/39555197729)
также прошёл до слияния. Автоматический ready_for_review run39555605053 остановлен
как дублирующий при неизменных inputs; отменённый run не объявляется успешным.
Полная нативная модель/Jenkins/Requests матрица ради слияния повторно не выполнялась.
Предыдущие evidence сохраняют собственные source commits и image IDs.

## Новые проверки слитого main

| Проверка | Результат |
| --- | --- |
| [Полный unit](unit-tests.json) | 171 tests, 0 failures/errors/skipped; hashes всех учтённых suite inputs неизменны |
| [Изолированный installed control](installed-control.json) | Verify0 → snapshot0 → repeat0 → strict diff1 → invalid baseline2 |
| [Документация и формат](completion-checks.json) | Contracts/schema/examples/links, команды/defaults/shell syntax, Black, diff check |
| [Сохранность](preservation.json) | 13 protected inputs, старый release/tag/default locks/images, proxy/model/dictionary/corpus и 7 чужих контейнеров сохранены |

Unit выполнен на host macOS ARM64/Python3.12.14 с подготовленными pinned fixtures;
это отдельный результат от нативного Linux unit. Первый sandbox-запуск не смог
открыть локальные HTTP fixtures из-за запрета socket.bind; полный повтор с
доступом к loopback прошёл все 171 тест. Сырые assertion logs остаются приватными.

Control использовал launcher из merge-коммита, скопированный в отдельную установку,
Python `-I -S` и явный deployment неизменных опубликованных ARM64 v0.1.0 images.
Код старых images не выдаётся за новую сборку main или повтор AMD64 inference.
Нового import/pull/build не было; исходный release manifest сохранён.
На синтетическом Git-клоне проверены full values/context/category/coordinates/source/score
в JSON/HTML, приватные 0700/0600, безопасная console, 1 analyzed/1 inherited
для strict diff, invalid baseline, неизменность входа и cleanup своего Compose project.
Новые контейнеры запускались с внутренней сетью без внешнего доступа; page cache
не сбрасывался. Полные отчёты не публикуются.

## Текущее состояние и границы

Поддержка CPU Linux AMD64 и нативная ARM64 регрессия находятся в `main`.
Версия проекта остаётся `0.1.0`, опубликованный v0.1.0 — прежний ARM64-комплект.
Нового release/tag/GHCR push/OCI index и замены default deployment не было.
Слияние исходников не заменяет установленную поставку; для будущей публикации
нужны отдельное решение, versioned build и проверка реально публикуемых IDs.
Images disposable native runner не обещаны доступными после job.

[Матрица приёмки и измерений](../readiness-matrix.md) сохраняет границы выводов;
TP33/FP13/FN4 и полный Requests119/13/0,612 candidates относятся к прежним
нативным прогонам. Прежние четыре native-риска и
[решение о certifi/ограничении HTTPS](../certifi-advisory.md) сохранены;
исправление этих библиотек не заявляется. Параметры сервера и Jenkins-агента
пока не выбраны; опорный AMD64 стенд — native Ubuntu24.04 GitHub Actions.
Физический закрытый сервер, rootless/userns/другие CPU/PKI/ACL требуют пилота.
[Инструкция сервера](../../../docs/admin/linux-amd64.md),
[Jenkins](../../../docs/admin/jenkins.md).
