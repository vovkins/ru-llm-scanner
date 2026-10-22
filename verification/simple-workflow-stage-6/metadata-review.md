# Проверка стабильности rule_id

Native run39835960260/source d59a69d сравнен по2805 synthetic находкам трёх
комплектов AMD64/ARM64. Category/start/end/value SHA/source совпадают; максимальное
отличие score3.3974647521972656e-06, в пределах frozen1e-5. Exact TP/FP/FN совпали.
Полный run FAILED из-за ошибочной подготовки walkthrough; это не runtime pass.

| Комплект | Frozen case | AMD64 rule_id | ARM64 rule_id |
| --- | --- | --- | --- |
| old | unpadded-declared |base64.declared|null|
| old | typed-secret-json |base64.declared|null|
| content | оба |null|null|
| logistic | оба |null|base64.declared-json|

В этих строках score0.95 и все поля находки, кроме rule_id, одинаковы.
Установленный Presidio EntityRecognizer.remove_duplicates использует set;
RecognizerResult equality/hash учитывают category/start/end/score, а metadata
игнорируют. Выбор дубликата сохраняет metadata первого экземпляра. Это уже
присутствует в старом комплекте. Historical source/locks/images не исправляются.

Предлагаемая ограниченная адаптация нового API: для уже возвращаемой structural
находки с точным совпадением category/start/end выбирать существующий upstream
Base64 declaration rule из document-pass/public analyze_declared. Metadata map
не передаётся в merge, не добавляет находки и не меняет category/span/score/text
или source. Logistic coefficients и frozen corpus прежние. На новом API строго
проверяются стабильные rule_id, raw/patched common fields и все точные метрики.

Владелец явно согласовал2026-10-22: «Согласовать: исторический drift описать,
новый исправить». Historical-only исключение ограничено этими двумя case IDs и
парой rule_id null/base64.declared при полном совпадении остальных identity fields;
score сохраняет прежний tolerance1e-5. Content/logistic rule_id проверяются строго. Нельзя скрывать
расхождения удалением rule_id из receipts или изменением старых образов/аннотаций.

## Частный проверенный прототип

[Patch-прототип](proposed-analyzer-api-base64-v2.patch) перенесён в отдельный
review v2; root source lock и текущие образы ещё не переключены. [Безопасная сводка](metadata-prototype.json): настоящий
локальный ARM64/model run на неизменном старом package/model image с новым source
overlay, network=none,2CPU/3GiB.65 raw/patched common-field parity cases прошли,
NER ready; exact33/14/4 и2511/3/1 сохранены. Оба проблемных новых declaration
rule_id стали base64.declared-json; NER и logistic-cascade fragment не меняются.
Это прототип, не freshly-built native image acceptance; повторная стабильность
и новые нативные комплекты пока не подтверждены. Текущие pins/images не менялись.

Новый [review](../../examples/upstream/base64-metadata-review.json) и API v2
сохраняют исходный stage5 review/API v1 без изменений. Native приёмка v2 pending;
root pin пока старый. [Отдельное NER/Base64 уточнение](criterion-amendment.md) прежнее.

Local source preparation v2:106sources/0blockers; source lock23903ac45dd82fb1b2839bd841d8faa5818e38d6bfabc4ad19607bdd69321f2c
отличается от stage5 d663 только patches.259unit/0skip/0missing пройдены;
отдельные regressions проверяют canonical metadata, запрет NER/native relabel,
неизменность входных результатов и узкий historical-only scope.
