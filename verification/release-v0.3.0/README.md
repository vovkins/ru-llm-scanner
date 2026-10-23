# Подготовка v0.3.0

План [#51](https://github.com/vovkins/ru-llm-scanner/issues/51) согласован владельцем
2026-10-23, включая слияние проверенного релизного PR и публикацию после gates.
Релизный PR #52 слит после успешных native smoke39924875081 обеих CPU;
267unit/0skip/0missing и19case Make walkthrough с empty-store import/control.
[Подготовка](preparation.json) и [сохранность](preservation.json) проверены.
Полная релизная сборка/приёмка и публичные проверки ещё не завершены.
[История попыток](attempt-history.md): первый full run отменён до assets из-за
исправления атрибуции notices; это не успешная приёмка.

Исходная точка: main `70bdabb93efffb295e3e7596428c4aa859d2ea9d`.
Ветка `codex/release-v0.3.0`. Версия0.3.0, exact Analyzer9e47/logistic/APIv2;
model/dictionary/dependency/corpus pins сохранены. Меняются version labels и
соответствующие recipe hashes. Прежние релизы и их evidence не переписываются.

Релизная адаптация экспортирует images фактического Make build/walkthrough;
эти же IDs проходят direct Jenkins и остальные gates, замораживаются и
публикуются без пересборки. Исторический explicit import остаётся отдельной
проверкой совместимости. [Руководство выпуска](../../docs/admin/releases.md).

Сводки/run IDs/digests добавляются только после реального выполнения. Raw reports,
значения находок, environment, credentials и build cache не публикуются.

## Полная приёмка кандидата

[Native run39927948569](https://github.com/vovkins/ru-llm-scanner/actions/runs/39927948569)
SUCCESS AMD64/ARM64/compare на image source5be9ad8; [сводка](functional-summary.json),
[строгая сверка](validated-build.json).267unit/0skip/0missing;478core/96NER/489Base64;
real NER65 raw/patched,77NER/4dictionary; strict repeat2561 finding records.
Model cross maximum2.1457672119140625e-6; Requests632,119analyzed/13unsupported/0errors,
cross4.5299530029296875e-6<1e-5. Code-v1 остаётся33/14/4; малыеBase64 11/3/1,
2500 повторений — stress. Два Jenkins adapters AMD64 по13 completed cases, acquisition0.

[Final frozen archive39935005472](https://github.com/vovkins/ru-llm-scanner/actions/runs/39935005472)
SUCCESS обеих CPU: полные file SHA/extract/OCI labels, отдельные пустые
Docker/containerd stores, verify/snapshot/strict/negative0/0/1/2. Точные архивы:

- AMD64 `e2d3699f710583aa855abb6f7806f80db325b080b00535112581c7d5552336a4`;
- ARM64 `1854a7c764b545644d44963ef7e1e7d012cc782a77ace6a84f40845a4a2be240`.

[Advisory review](advisory-review.md) завершён: новый Brotli CVE измеренно вне
штатного пути исполнения; библиотека не исправлена. [Native sources](native-source-reuse.json)
повторно связаны с фактическими обоими inventories.110 material hashes сохраняются.
GHCR/tag/public Release ещё не опубликованы; следующие receipts добавляются по факту.
