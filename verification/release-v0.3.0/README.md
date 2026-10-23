# v0.3.0: простой запуск и Analyzer logistic

[Релиз v0.3.0](https://github.com/vovkins/ru-llm-scanner/releases/tag/v0.3.0)
опубликован **2026-10-23T10:10:49Z**,19assets, ordinary release.
[План #51](https://github.com/vovkins/ru-llm-scanner/issues/51) выполнен;
релизный PR #52 слит после native smoke. **Все финальные native/public/Git-tag gates SUCCESS.**

Неизменяемый image/source/tag: `5be9ad8be41e5ccad36d4dcea2b1fe96d7d06c39`.
Последующие main commits содержат документацию, receipts и проверки распространения;
все110 image/build material hashes совпадают с source. Producer workflows имеют
собственные SHA в [provenance](release-provenance.json); они не перемещают tag и
не заменяют images. [История попыток](attempt-history.md) сохраняет отменённые
прогоны отдельно; они не выдаются за passed.

## Пользователю

[Обычный запуск](../../docs/admin/releases.md) — доверенный Git checkout v0.3.0,
`make build` → `make test` → `make scan`/`make diff`. Сборочному серверу нужен
интернет; во время scan acquisition нет. Make собирает из исходников, GHCR pull
проверяется отдельно. Для Jenkins — прямой CLI с process0/1/2.

Ручной deployment.json/wheel/выбор image ID не нужен в основном пути.
Полный архив имеет отдельный advanced explicit import/verify маршрут; он не
создаёт Make-установку, а GitHub source ZIP без .git не обещан как Make-путь.

## Публичные образы и assets

| Package | Общий OCI index0.3.0 |
| --- | --- |
| `ghcr.io/vovkins/ru-llm-scanner` | `sha256:1809827b4b75c197245561a226c5b99e65f4fed0a64c8e3e0f99911ecded670f` |
| `ghcr.io/vovkins/ru-llm-scanner-analyzer` | `sha256:fcd918955e11208c3f10af654f72d777bd789770266ae64a7b47279695a2479d` |

Каждый index содержит ровно linux/amd64+linux/arm64; есть отдельные versioned
`0.3.0-amd64`/`0.3.0-arm64`. `latest` не создавался. Index/manifest/config digests
различаются: точное соответствие — [registry mapping](registry-images.json).
Между frozen приёмкой и push images не пересобирались.

19assets: два полных платформенных архива, manifests/platform receipts, wheel,
corresponding native sources, три license/notices файла, acceptance,
registry receipts/mapping, provenance и [SHA256SUMS](SHA256SUMS).
Суммы содержат18 других файлов; сам checksum имеет отдельный GitHub asset digest.
Raw reports с values, environment, credentials и build cache не включены.

Архивы SHA256:

- AMD64 `e2d3699f710583aa855abb6f7806f80db325b080b00535112581c7d5552336a4`;
- ARM64 `1854a7c764b545644d44963ef7e1e7d012cc782a77ace6a84f40845a4a2be240`.

## Что действительно выполнено

| Gate | Успешный run | Область |
| --- | --- | --- |
| Финальные native build/test | [39927948569](https://github.com/vovkins/ru-llm-scanner/actions/runs/39927948569) | AMD64/ARM64, фактические Make images, core/model/CLI/fault/capacity/Jenkins/Requests/cross |
| Окончательные архивы | [39935005472](https://github.com/vovkins/ru-llm-scanner/actions/runs/39935005472) | Полные SHA/download/extract, labels/source, два пустых Docker/containerd stores, Brotli probe |
| GHCR publisher | [39936095023](https://github.com/vovkins/ru-llm-scanner/actions/runs/39936095023) | Четыре platform tags, два indexes, anonymous native tag/index/digest pulls и installed controls |
| Public assets/images | [39937473313](https://github.com/vovkins/ru-llm-scanner/actions/runs/39937473313) | Anonymous full platform downloads, SHA, pull и actual verify/snapshot/strict/negative0/0/1/2 обеих CPU |
| Чистый published Git tag | [39937477276](https://github.com/vovkins/ru-llm-scanner/actions/runs/39937477276) | Source5be9ad8, Make build/test/scan,19cases/9literal blocks,267unit/0skip,22own projects cleaned и acquisition0 на CPU |

Полная native приёмка:267unit/0skip/0missing на платформу; upstream478core/96NER/
489Base64; real-model65 raw/patched cases,77NER/4dictionary parity. Два повторных
model запуска сравнили2561 finding records строго, включая rule_id; repeat score
delta0. Между CPU maximum2.1457672119140625e-6. Отдельные77NER migration cases:
maximum3.4570693969726562e-6. Решения/category/value/span/source/rule_id совпали;
confidence tolerance1e-5 не разрешает иные различия.

Pinned Requests b25c87d:119analyzed/13unsupported/0errors,632кандидата обеих CPU;
максимальная cross score delta4.5299530029296875e-6<1e-5. Это reference parity
публичного корпуса без ground truth истинных секретов. Настоящий Jenkins AMD64:
13direct+13legacy completed cases, acquisition0; production/ARM64 Jenkins не заявлены.
Реальный published v0.2.0 → v0.3.0 → v0.2.0 → v0.3.0 с возвратом к прежнему baseline
прошёл обе CPU. Старый baseline новым engine отклонён.

После публикации **два больших платформенных архива полностью скачаны на native
runners** и проверены фактически. Ещё17assets, включая398330836-byte native sources,
полностью скачаны без credentials на локальном проверочном host и сверены с
GitHub digests/SHA256SUMS: [точная область аудита](public-assets-audit.json).
Это разные проверки: Git-tag walkthrough заново собирает source images;
проверки GHCR используют уже опубликованные platform contents.

## Качество и принятые границы

Code-v1: **33TP/14FP/4FN**.18 малых новых Base64 случаев: **11/3/1**;
2500 повторений одного dense примера — stress, не2500 независимых наблюдений.
Полные Base64 stress totals2511/3/1 не выдаются за универсальную точность.
[Принятое NER-пересечение](../simple-workflow-stage-6/criterion-amendment.md)
сохраняет полное union coverage и точные FP/FN, не меняет разметку. Новый engine
строго стабилен по rule_id; historical-only поправка не распространяется на него.

Analyzer exact9e47e6594ba3d9616ba90720994ced008335416c/logistic/APIv2.
Модель/словарь/dependencies/коэффициенты/пороги/корпуса не обновлялись релизом.
Version labels и непосредственно связанные recipe hashes согласованы;
license attribution приведена к этому exact source, MIT/third-party notices сохранены.
[Прежние native риски](../operations-dependencies/risk-acceptance.md) и
[certifi/HTTPS решение](../linux-amd64/certifi-advisory.md) не объявлены исправленными.
Новый Brotli CVE [измеренно вне штатного пути исполнения](advisory-review.md),
сама библиотека уязвима для других потребителей. Это не универсальное исключение.

Native стенды — Ubuntu24.04/rootful Docker/non-root. Целевой production hardware,
GPU, другие корпоративные ACL/PKI/daemon settings не объявлены проверенными.
HTML проверен статически: CSP/cards/full synthetic value/no external assets;
новая browser acceptance не выполнялась. Cgroup measurements не являются
hardware cold-boot benchmark или точным пиком физического build storage.

## Сохранность и receipts

[Итоговая сохранность](preservation.json):532 прежних protected inputs,
7 чужих containers (Config/HostConfig/image/Running/StartedAt),58 прежних image IDs,
proxy HEAD9e47, v0.1.0/v0.2.0 Git tags/assets7/19 и8 прежних GHCR manifests неизменны.
Production jobs не запускались, внешняя инфраструктура не менялась.
Новая версия требует нового полного clean snapshot для baseline; автоматического
продвижения baseline нет. Старые готовые установки/образы сохранены для отката.

[Acceptance до push](release-acceptance.json) и manifest kind/flags описывают
момент заморозки; live publication подтверждают registry/provenance/public receipts.
`registry-control-ARCH.json` — исходный publisher installed control; отдельные
anonymous controls включены в [provenance](release-provenance.json), public controls
лежат в public-ARCH. Существующие immutable assets не заменялись другими bytes.

[Итог после публикации](post-publication-summary.json), [функциональная сводка](functional-summary.json),
[строгая build сверка](validated-build.json), [native sources](native-source-reuse.json),
[Git-tag AMD64](git-tag-amd64.json), [ARM64](git-tag-arm64.json).
