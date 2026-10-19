# Итоговая приёмка первой версии

Этап 7 согласован в [#13](https://github.com/vovkins/ru-llm-scanner/issues/13)
2026-10-19. Проверено: macOS Apple Silicon, Docker Desktop 29.6.1 / Compose 5.2.0,
CPU Linux ARM64, host Python 3.12.14 / container Python 3.11.16. Итог относится
к этой среде и согласованной области текстовых Git-объектов. Версия остаётся
`0.1.0.dev0`, PR подготовлены последовательно и автоматически в main не слиты.

## Свидетельства

| Артефакт | Что подтверждает |
| --- | --- |
| [Unit](unit-tests.json) | 131 tests, без failures/errors/skipped |
| [Production acceptance](acceptance-verification.json) | 16 сквозных запусков, private reports, input fingerprints и чужие ресурсы |
| [Upgrade/rollback](upgrade-verification.json) | 8 реальных шагов, old/new profile и правильные/неправильные baseline |
| [Source review](source-review.json) | Реальные SHA, 95/97 source files, 18 различий, прежние модель/dependencies/notices |
| [Historical source lock](old-source.lock.json), [patch record](old-api-metadata.patch.json) | Точные historical bytes и API metadata adaptation до/после без fuzz |
| [Historical runtime](old-runtime.lock.json), [deployment](old-deployment.json) | Реальные image/platform IDs, inventory, weights, подпись и policy hash |
| [Raw/patched v0.4.0](old-parity.json), [текущей версии](current-parity.json) | На каждой версии 77/77 NER parity, 4 dictionary cases и исходные quality gates |
| [Upstream v0.4.0](old-upstream-tests.json), [текущей версии](current-upstream-tests.json) | 394 / 478 passed, один применимый regression subset из 7 файлов |
| [Code-v1 v0.4.0](old-code-verification.json), [текущей версии](current-code-verification.json) | Независимые exact metrics и отдельная 46/46 direct parity на каждой версии |
| [CLI v0.4.0](old-cli-verification.json), [текущей версии](current-cli-verification.json) | По 9 offline сценариев установленного неизменённого wheel |
| [Прогон инструкций](documentation-verification.json) | Новый wheel/context/build, export/import и snapshot/diff с config/baseline |
| [Финальная сверка](completion-checks.json) | Хеши/IDs/пакет сохранены, собственные ресурсы убраны, чужие проекты неизменны |

Это verification records, не готовый импортируемый release. Historical source
lock с относительными build inputs восстанавливается helper-ом по
[инструкции](../../docs/updating-analyzer.md); не используйте папку evidence как
build context. Полные synthetic reports/fixtures и assertion logs остались в
ignored `.build/stage-7/`, без публикации исходных значений в evidence.
Patch record хранит UTF-8 строки с переводами строк, сохраняя значимые пробелы
unified diff; SHA-256 проверяется после `''.join(patch_lines).encode('utf-8')`.

## Сквозные сценарии

Подтверждены snapshot A → diff A/B → diff B/C, exact rename с previous raw path,
delete, mode/type changes и A=B. Изменение только соседнего комментария не
ограничило анализ diff-строкой: прежняя строка с credential найдена в полном
файле. Многострочный ключ сохранён полностью. Явный merge target проверялся
от выбранного пользователем A с совместимым baseline.

Историческая граница показана отдельным Git-графом: чистое A → commit с секретом
→ чистое B с тем же деревом, что A. Diff A/B корректно не нашёл итоговых изменений;
snapshot промежуточного commit обнаружил секрет. Это подтверждение границы
режима, а не аудит всей истории.

Unicode/combining/CRLF, CP1251, BOM UTF16, файлы без расширения и два raw paths с
одинаковым display path сохранили отдельные IDs/полные значения. PDF/archive/LFS/
submodule/symlink и explicit exclude отражены в coverage. Symlink на доступный
untracked canary не читался. Working/staged/untracked/metadata fingerprint не менялся.

Hostile include/config/hooks/fsmonitor/filters/textconv/credential helper/remote
и replace/grafts не выполнились и не подменили дерево. Marker в доступном output
не создавался; исходный credential сохранился в находках, untracked key не попал
в результат. Отсутствующий blob при promisor/remote настройках дал код 2 без
внешнего fetch. Profile mismatch также отклонён. Более широкая матрица сбоев,
OOM/signals/parallel/isolation уже подтверждена в [этапе 6](../stage-6/README.md);
продуктовый runtime на этапе 7 не менялся.

## Реальное историческое обновление

Read-only GitHub API и локальная ancestry-проверка подтвердили отсутствие нового
upstream: main — закреплённый `da4f50a87ddf8a6c160c5f1893f5bf526f713d1c`, все
8 других веток — его предки. Пользователь отдельно согласовал последовательность
**v0.4.0 `dd403a182494a1c439f552666f21e7c4c8e7e080` → da4f50a → v0.4.0**.

Менялись реальные словарная политика, LOGIN/instruction handling, result merging
и связанные tests/evaluation. Модель, закреплённые зависимости и notices прежние.
Historical image собран из 95 allowlisted tracked файлов; metadata patch
адаптирован по пяти точным anchors. Обычный seal проверил источники/пакеты/
модель/spaCy/словарь/платформу. Повторный seal текущего image полностью совпал
со штатным runtime lock. Это не замена digest/label для имитации версии.

Historical Analyzer platform ID:
`sha256:f0e82e7e83bbcc49e74f364507593289f6da826c0ff1e29843b116b80d1401b8`.
Текущий остаётся:
`sha256:dac76ca6f7f37d61f7a3ad4db1d56d68dcad14d9e44354252dcfbf3c208c5104`.
Old profile: `a421143128cc3978f80229815eaa0648ebe672d330a0558bcc4122afa44e2959`;
current profile: `172554ef20c07cf32e15cd97cd368a2510de49ab824ae2b339258078730a1864`.
Platform/reference IDs отдельно зафиксированы в locks.

Один scanner wheel/dependency set работал с двумя bundles. Последовательность:
old snapshot A/old diff A→B; отказ old baseline на current; новый snapshot B/
current diff B→C; отказ new baseline после rollback; отказ baseline другого A;
успешный old diff B→C со старым baseline B. Profile и assurance восстановлены.
Штатные locks/модель/правила/пороги/corpus и соседний proxy не менялись.
Ни Git, ни pipeline, ни renderer не требовали переписывания.

## Качество и границы готовности

На обеих версиях frozen code-v1: **37 ожидаемых мест, TP 33 / FP 13 / FN 4,
exact precision 71.74%, recall 89.19%**. Полностью пропущен телефон; bearer,
base64 и INN имеют ошибки категории/границ, есть дополнительные срабатывания.
Разметка и thresholds не менялись ради метрик. 46/46 direct parity и 77/77
raw/patched parity подтверждают соответствие механизму, не отсутствие ошибок.

Распознавание/JSON/HTML/CLI/Docker/baseline и перенос проверены в согласованных
границах. Renderer не менялся, поэтому прежняя [визуальная QA](../stage-5/README.md)
остаётся применимой; direct file:// в встроенном браузере не проверен из-за
URL policy, обхода не было. Jenkins example повторно сверен с текущим CLI и
прежней локальной последовательностью; настоящий Jenkins/RBAC/plugins не тестировались.

GPU, AMD64, Windows-native, Linux-host UID mapping, иная корпоративная PKI/proxy,
физически отдельный offline host и другой image store не проверены. Source locks,
images и baseline должны приходить из доверенного процесса: SHA-256 не подпись.
Host/daemon доверенные; object store должен быть неизменен снаружи во время scan.
SIGKILL/daemon loss может оставить ресурсы для ручного cleanup. Очередь не
ограничивает всю RAM результатов/модели; CPU join может продлить deadline;
JSON/HTML атомарны отдельно, infrastructure exit 2 важнее прежнего clean файла.

Release/registry, merge PR, лицензия, приватный vulnerability contact и действующие
GitHub/Jenkins настройки не изменялись. Эти решения остаются у владельца.
