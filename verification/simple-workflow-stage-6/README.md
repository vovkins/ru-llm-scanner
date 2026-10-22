# Этап 6: перенос logistic, откат и Jenkins

Согласованные [#49](https://github.com/vovkins/ru-llm-scanner/issues/49) и
[общий цикл #38](https://github.com/vovkins/ru-llm-scanner/issues/38).
Изменения находятся в [draft PR #50](https://github.com/vovkins/ru-llm-scanner/pull/50)
поверх #41/#42/#44/#46/#48. Все PR остаются без слияния; опубликованные
v0.1.0/v0.2.0, main, registry и соседние проекты не менялись.

## Результат переноса

Текущие неопубликованные исходники закрепляют exact upstream
`9e47e6594ba3d9616ba90720994ced008335416c`, принятую владельцем политику `logistic`
и metadata API v2. Source lock SHA-256:
`23903ac45dd82fb1b2839bd841d8faa5818e38d6bfabc4ad19607bdd69321f2c`.
106 применимых файлов, новые модули, шесть upstream test files и настройки
перенесены через прежний export/prepare/verify. Git reader, pipeline, report
schema и renderer не переписывались. Модель, словарь, packages, коэффициенты,
пороги и frozen annotations сохранены.

Пользовательский маршрут — `make build/test/scan/diff`. Обновление proxy остаётся
[процедурой сопровождающего](../../docs/reference/upstream-update.md), с whole-tree
review и отдельным кандидатом; произвольный main/latest автоматически не принимается.
Подтверждён один настоящий перенос, а не гарантирована совместимость любого будущего API.

## Полная нативная приёмка

[Run 39848479099](https://github.com/vovkins/ru-llm-scanner/actions/runs/39848479099),
source **9f384a8423f7da8bf55bb8b7565222c02339768d**, SUCCESS на native
Ubuntu 24.04 AMD64/ARM64. [Run receipt](native-run.json),
[AMD64](native-amd64.json), [ARM64](native-arm64.json),
[строгая межплатформенная сверка](cross-platform.json).

| Проверка | Результат на обеих CPU |
| --- | --- |
| Три отдельные установки old/content/logistic, фактические images и readiness | Passed |
| Старый make test | 244 unit, 0 skips/errors, 6 групп passed |
| Новый make test на каждой policy | 261 unit, 0 skips/errors/missing groups, 6 групп passed |
| Новые Base64 upstream tests на каждой policy | 489 passed, 0 skips |
| Upstream core / NER regressions | 478 / 96 passed, 0 skips |
| Реальная NER и raw/patched parity общих полей | 65 случаев на каждом из трёх комплектов |
| Прежняя upstream parity / dictionary / quality | Passed, 77 NER и 4 dictionary cases |
| Old → logistic → old → logistic | Реальные отдельные установки/IDs, исходные baselines повторно использованы |
| Baseline другого engine/profile | Отклонён с кодом 2 |
| Чистый checkout/HOME, буквальные Make/CLI примеры | 19 случаев, 9 блоков документации, без acquisition после build |
| OOM, отмена, partial output, capacity и cleanup | Ожидаемые коды, чужие ресурсы сохранены |
| Публичный Requests | 119 analyzed, 13 unsupported, 0 errors, 632 находки |

Проверены 2805 synthetic-находок, точные category/span/value hashes/source/rule_id.
Максимальная разница confidence между CPU — `3.3974647521972656e-06`, для
Requests столько же; допуск `1e-5`. В финальной попытке исторический rule_id drift
не воспроизвёлся; два ранее измеренных old-only расхождения сохранены в
[предыдущей scoped сверке](model-public-cross-api-v2.json) и
[расследовании](metadata-review.md). Новые metadata сравниваются строго.

## Качество, происхождение и ограничения

[Exact метрики и все изменения](quality.md): code-v1 **33 TP / 14 FP / 4 FN**
против прежних 33/13/4; 18 малых новых случаев **11/3/1**. Ещё 2500 TP —
повторения одного dense stress, не независимые quality samples.
[Согласованное NER-overlap уточнение](criterion-amendment.md) сохраняет exact FP/FN
и отдельно требует полного объединённого покрытия с прежними NER spans.
[Ожидания](expectations.md) и корпус заморожены до model runs.

Все 612 прежних semantic identities Requests сохранены. 20 добавок разобраны
по тем же Git blobs: 11 PEM, 2 data URI, 7 Base64-подобных test tokens;
четыре фрагмента сохраняют соседние native spans.
[Safe source review](public-added-source-review.json) не содержит значений.
Requests не имеет secret ground truth: эти кандидаты не объявляются истинными
секретами. [Текущий reference](requests-reference.json) применяется проверочным
helper по умолчанию; исторический 612-reference не менялся.

Upstream PR104: base da4f50a, merge9e47e65, 2026-10-21T19:20:10Z.
Закреплённые upstream docs заявляют генеративное происхождение без стороннего кода,
SHA-256 архива `08554f372dee79e51baaf8557457633b55aa2adaeb3916bfab5fb5564c9ad810`
и модуля `59e2b297abfa23c11afe1076201271e0d0adbebf6625bd34e65c59bf5fa4be38`.
Сам архив не опубликован; floating HEAD training inputs не позволяют побайтово
воспроизвести обучение. Notices/licenses и artifact closure прежние.
Принятые владельцем native/certifi ограничения не исправлялись и не скрываются.

## Jenkins и эксплуатация

[Настоящий Jenkins receipt](jenkins.json): AMD64, Jenkins LTS 2.580.1,
закреплённый controller digest/plugins, declarative validation и 13 завершённых
сценариев. Проверены process 0/1/2, strict baseline, invalid inputs,
unbuilt installation без старого report, parallel jobs, cancel, timeout и hard
agent loss с ограниченным operator cleanup. В console нет значений; private
artifacts содержат полные synthetic результаты. Baseline автоматически не продвигается.
Наблюдались 10 собственных Docker projects; acquisition attempts — 0.

[Прямой adapter](../../examples/jenkins/run_workflow_scan.py) использует trusted
установку/config/input/baseline вне очищаемого workspace. Старый explicit adapter
сохранён. [Руководство Jenkins](../../docs/admin/jenkins.md) описывает bind/UID,
ресурсы и ACL prerequisites. Production Jenkins, корпоративные ACL/PKI,
rootless Docker, GPU и настоящий ARM64 Jenkins не проверялись.
[Времена и ресурсы](resources.md) не являются SLA.

## Финальная привязка исходников

Материалы модельной приёмки:
[AMD64](material-inputs-amd64.json) / [ARM64](material-inputs-arm64.json).
После успешных gates source lock/API v2 перенесены побайтово из проверенного
кандидата; обновлены документация и reference helper. Заключительный чистый
native build/test/walkthrough этой финальной ветки ещё выполняется; завершение
задач и финальный material proof будут зафиксированы по его результату.

[Ревью](review.md), [история неуспешных попыток](attempt-history.md).
Frozen expectations/amendments сохраняют формулировки своих checkpoint;
актуальный итог находится здесь. Curated native receipts заменяют безопасные массивы более100 элементов
на count/hash; малые случаи, метрики и score maps сохранены полностью; полная сверка выполнялась по исходным
artifact JSON, их SHA сохранены. Raw reports, values, env, модель и container
logs не публикуются. Browser acceptance не выполнялась: ранее file:// был
заблокирован URL policy; static HTML checks не выдаются за browser pass.
