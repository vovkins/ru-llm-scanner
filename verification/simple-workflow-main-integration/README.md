# Интеграция простого запуска и обновлений proxy в main

Владелец 2026-10-23 явно согласовал последовательное слияние PR
#41/#42/#44/#46/#48/#50, проверку результата и актуализацию документации/задач.
Релиз, tags и публикация образов/GHCR не разрешены.

## Состав main

| PR | Принятый head | Merge-коммит main |
| --- | --- | --- |
| [#41](https://github.com/vovkins/ru-llm-scanner/pull/41) | `2ec86e11df8b` | `30efd5c0228173b2edeb55e3b443e9dcd25c1c10` |
| [#42](https://github.com/vovkins/ru-llm-scanner/pull/42) | `8dfa134f1df6` | `b7b970cf64e854267b6df0b9cd2970ec616c73c7` |
| [#44](https://github.com/vovkins/ru-llm-scanner/pull/44) | `4ef088b7475a` | `515595412debb9c68c8ca20ff8006111adc8f6b4` |
| [#46](https://github.com/vovkins/ru-llm-scanner/pull/46) | `d39c8e64fdf9` | `2121007da17776a911c602410b65789cc44bd5a1` |
| [#48](https://github.com/vovkins/ru-llm-scanner/pull/48) | `7045dd4fc7b2` | `f5ba37e44c580e0743fe80f909656b68a6179971` |
| [#50](https://github.com/vovkins/ru-llm-scanner/pull/50) | `9353a80bf795` | `640856f5bcfab70202e59af8ccb42011da09bd4c` |

Исходный main — `37e5e0e7dfd545941a6de008585e226b9271e5a0`.
Checkpoint после слияний — **`640856f5bcfab70202e59af8ccb42011da09bd4c`**.
Первый родитель каждого merge — предыдущий main, второй — точный согласованный
head. Каждое дерево совпало с принятым PR; итоговое полностью совпало с
`9353a80bf7956c394159e4dba29c35f81c798a3e`. Все6 heads являются предками checkpoint.
[Полные SHA и порядок](merges.json), [проверка дерева](merge-checkpoint.json).
Никаких конфликтов, force push или admin bypass; исходные ветки сохранены.
Branch protection отсутствовала, API rules вернул пустой список.

Все [109 принятых material inputs](accepted-materials.json) совпали сразу после
merge. Затем менялись только README/status docs/AGENTS и safe evidence.
Детекторы, Git reader, pipeline, schema/renderer, source lock/API patches,
model/dictionary/dependencies, коэффициенты и frozen corpus не менялись.

## Проверка интеграции

Статусы README и документации обновлены: новый Make/CLI и9e47e65/logistic
находятся в main, опубликованный v0.2.0 остаётся прежним выпуском.
README входит в package provenance, поэтому выполняется новый clean native
build/test/walkthrough main на AMD64/ARM64. Итог пока не заявляется успешным;
safe receipts будут добавлены после завершения. Local unit/contracts/docs/format
также проверяются отдельно. Старые JSON receipts не переписываются.

Шесть автоматических ready_for_review прогонов отменены как дублирующие
проверки уже принятых heads, [IDs и причина](redundant-ready-runs.json).
Они не считаются успешными. Полная прежняя native приёмка engine-update
[39848479099](../simple-workflow-stage-6/README.md) остаётся измерением source9f384a8:
три kits,261new unit/0skip,489 Base64 tests на policy,65 real raw/patched cases,
77 NER/4 dictionary, настоящий откат, capacity/faults, Requests632 и13 Jenkins
AMD64 сценариев. Frozen annotations и согласованные узкие критерии прежние.
Без изменения runtime inputs эта тяжёлая матрица не повторяется ради merge;
применимость будет подтверждена final material proof.

## Границы результата

Новый пользовательский маршрут — make build/test/scan/diff, без обязательных
ручных deployment.json/hash/wheel шагов и отдельного offline набора команд.
Сборочный сервер использует интернет; готовый scan работает локально без acquisition.
Source compare/review/prepare не принимает произвольный future main автоматически.

Версия остаётся0.2.0 в исходниках, нового выпуска нет. Опубликованные v0.1.0/v0.2.0,
их images/assets/tags и действующие чужие установки сохраняются. Слияние исходников
само по себе не переключает установленный комплект или baseline; оператор выбирает
доверенный checkout, выполняет make build/test, затем полный clean snapshot при
смене engine/profile. [Обновление и откат](../../docs/admin/updating-analyzer.md).

Известные FP/FN, ограничения provenance обучения и принятые native/certifi риски
[сохранены](../simple-workflow-stage-6/quality.md). Browser/production Jenkins/
corporate ACL/PKI/rootless/GPU/ARM64 Jenkins не объявляются заново проверенными.
Полные отчёты, environment, модель и container logs не публикуются.
