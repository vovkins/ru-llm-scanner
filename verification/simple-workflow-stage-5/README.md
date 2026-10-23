# Этап5: управляемая подготовка обновлений proxy

Согласованный [#47](https://github.com/vovkins/ru-llm-scanner/issues/47),
общий план [#38](https://github.com/vovkins/ru-llm-scanner/issues/38),
[draft PR #48](https://github.com/vovkins/ru-llm-scanner/pull/48).
Базаd39c8e64fdf9edc9f60e4305844f066a655c91f1 (#45). Все PR
#41/#42/#44/#46/#48 остаются без слияния, main37e5e0e не меняется.

Реализован [stdlib compare/prepare](../../docs/reference/upstream-update.md),
[strict schema](../../schemas/upstream-update-v1.schema.json) и
[review настоящего обновления](../../examples/upstream/README.md).
Все25 changed paths **da4f50a→9e47e65** рассмотрены, curated export97→106,
добавлены9 новых файлов, весь словарь/NER model/dependencies сохранены.
Кандидат явно выбирает logistic; **текущий engine остаётся da4f50a**.
Source_prepared не является принятием модели, deployment или baseline.

## Финальная native приёмка

[39813337053](https://github.com/vovkins/ru-llm-scanner/actions/runs/39813337053),
exact source **1ad574538a807bdc790774d240099bd2d3f20b97**, SUCCESS AMD64/ARM64.
[Run](native-run.json), [AMD64](native-amd64.json), [ARM64](native-arm64.json).
Все [106 material inputs](material-inputs.json) и [5 дополнительных update inputs](update-inputs.json)
(schema/test/review/patch/описание) совпадают с текущим source.
Последующие docs/evidence commits не меняют эти bytes и не перемещают принятые images/source.

Стенды native Ubuntu24.04, rootful Docker29.6.1, Python3.11/non-root оператор.
Новый отдельный bare-клон получает два exact SHA явно до проверки; затем
compare/prepare работают с acquisition guard и без Docker/pip/curl/wget/fetch.
Файловая inventory всего входа совпадает до/после, изменений нет.

| Проверка на каждой CPU | Результат |
| --- | --- |
| No-review compare2:25 изменений, новая зависимость/настройка/patch conflict видны | Passed |
| Reviewed compare0, exact hash-bound applicability каждого пути | Passed |
| Prepare0 ×2: оба source contexts проходят прежний verify_context | Passed |
| Повторный content manifest и profiles независимы от имени output | Passed |
| Каталог4 public SOURCE_* совпадает с upstream, private import удалён | Passed |
| Новые modules/resources/tests/settings и106 sources сохранены | Passed |
| Старый lock/model/requirements/dictionary/три прежних patches не переключены | Passed |
| Explicit make build → make test с прежним engine da4f50a | Passed |
| Missing installation/test assets, corrupt assets/env →2 | Passed |
| Explicit build repair без смены image IDs → повторный прямой test0 | Passed |
| Suite SIGTERM2 и очистка только собственных projects | Passed |

В каждом успешном make/direct test **244unit /0skip /0missing**, шесть групп
passed,9 runtime own projects,2 parallel scans, настоящая старая модель для
snapshot/HEAD/diff/strict baseline/config/timeout/cancel. Два успешных suite
на CPU плюс ожидаемый cancelled suite. Source-only кандидат **не исполнялся**
как новая модель; его API/runtime/quality/Requests/Jenkins/rollback — этап6.

## Повторяемость кандидата

Одинаковый content SHA на локальном source-only, AMD64 и ARM64:
`22308ab2cea9e950ebcf9aef196930dffb2300720ffdde28958881204f86d17e`.

Common candidate source lock:
`d663da2368b6a467b365c32b16283d1206c4098afde1fa01cd3544ab75137cb1`.
Отдельные context manifests обоих профилей связаны с ним в receipts.
[Локальный proof и три реальные schema instances](local-source-only.json).
[Intermediate probe](local-source-intermediate.json) относится к варианту
до финального удаления private enum dependency, не подменяет финальный receipt.

Replacement patch переносит пять metadata групп на новую версию server.
Runtime adapter использует4 public constants; прежний `_KNOWN_SOURCES` только
сопоставляется статическим gate для данного exact upstream, в Analyzer не импортируется.
Остальные3 patches прежние. Общий prepare_payloads перепроверяет все bytes/constraints/
model и переиспользует прежний generator/verify, без второй build подсистемы.

## Прочие проверки и границы

[Local244/0skip](local-unit-check.json),19 meaningful update regressions;
[docs74commands/58shellblocks/19defaults](documentation-check.json),
[contracts/links/format/schema](static-checks.json), [fast CI](fast-run.json),
[focused review](review.md). Report schema/renderer и детекторы scanner не изменены.
Browser acceptance заново не выполнялась и source checks её не заменяют.

[Времена](timings.json): полный source+current-engine acceptance333.448s AMD64,
360.112s ARM64. First suite68.423s/77.360s; repeat65.060s/76.633s.
Peak RSS не снимался, performance SLA не заявлен.

[Attempt history](attempt-history.json) сохраняет failed39810713533 до image build:
строгая input inventory обнаружила изменение после initial fetch. Первая версия
не записывала конкретные changed paths. Background maintenance — предполагаемая
подготовительная причина, не доказанная атрибуция конкретного файла. Explicit fetch
получил --no-auto-maintenance; changed-path диагностика добавлена, сравнение всех
файлов не фильтровалось. Intermediate и final native inventories неизменны.
Ни один failed run не объявлен успешной приёмкой.

[Preservation](preservation.json):44 из45 исходных protected inputs побайтово прежние.
Единственный scoped diff — upstream.py: общий verified prepare_payloads и цифры
в PRESIDIO environment names. Pins/model/dictionary/corpus/requirements/default
locks/renderer/Git/pipeline не изменены. Proxy HEAD прежний;7 чужих контейнеров
без изменения Running/StartedAt/Config,69 старых уникальных images сохранены;
v0.1.0/v0.2.0 identities/assets прежние. Raw reports/logs/contexts/model/env не
публиковались. CI contents:read, release jobs skipped, GHCR/images/tags/release
publication и merge отсутствуют. Принятые certifi/native риски не исправлялись.

[Следующий план #49](https://github.com/vovkins/ru-llm-scanner/issues/49) содержит
24 pending пункта: настоящее content/logistic сравнение, качество и ресурсы,
свежий Make/CLI/Jenkins pilot, baseline и обновление/откат. Он ждёт отдельного
явного согласования. Из подготовки candidate принятие logistic автоматически не следует.
