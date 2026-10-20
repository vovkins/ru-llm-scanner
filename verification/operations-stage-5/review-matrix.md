# Итоговые замечания и подтверждения

Состояние кандидата `e5e3115`, приёмка 2026-10-20. «Исправлен» ниже означает
исправление в проверенном комплекте. Затем стек PR отдельно согласован и включён
в `main`: [интеграция](../operations-main-integration/README.md).
[Исходное ревью](../../docs/review/README.md) на `336feb6` и исторические
воспроизведения сохранены. Применимость evidence к кандидату подтверждена
[манифестом](candidate-manifest.json) и [сверкой наборов](evidence-reuse.json).

| ID | Приоритет | Итоговый статус | Изменение и основание |
| --- | --- | --- | --- |
| RV-01 | P1 | Исправлен | [Jenkins adapter](../../examples/jenkins/run_scan.py) строго проверяет summary/exit/artifacts, invalid stdout не даёт 0; [unit 155/0 skipped](../operations-dependencies/unit-tests.json), [extras](../operations-dependencies/extras-verification.json) |
| RV-02 | P2 | Исправлен | [Launcher strict JSON](../../scripts/docker_scanner.py): regular nonblocking/no-follow FD, bounded read, отказ FIFO/oversize; unit и [Compose](../operations-dependencies/docker-verification.json) |
| RV-03 | P2 | Исправлен | [Dev recipe](../../docker/scan-test.Dockerfile) содержит pinned jsonschema, curated copy включает schema; [реальный scan](../operations-dependencies/scan-verification.json) и [исправления этапа 2](../operations-stage-2/README.md) |
| RV-04 | P2 | Усиление выполнено | [Общий helper](../../scripts/parity_verification.py): allowlisted input, non-root, pull never, actual ID, уникальное имя/owned cleanup; [77 NER/4 dictionary](../operations-dependencies/offline-verification.json) |
| RV-05 | P2 | Политика унифицирована | [Python writer](../../src/ru_llm_scanner/output.py) и launcher отклоняют публичный/чужой output без chmod/chown; unit/extras и [новый control](control-verification.json) |
| DOC-01 | P2 | Исправлен и пройден | [Fresh build](../../docs/admin/build.md) проводит один новый runtime/deployment; [fresh walkthrough](../operations-dependencies/fresh-walkthrough.json) и [ready walkthrough](../operations-dependencies/ready-walkthrough.json) на checkpoint `2588571` |
| DOC-02 | P2 | Документация подготовлена | [README](../../README.md), [две роли и справочник](../../docs/README.md), [About-текст](../../docs/about.md); GitHub metadata не менялись |
| TEST-01 | P2 | Предусловие явно сохранено | Prepared `.build/analyzer` нужен части unit; [инструкция](../../docs/development.md), полный результат 155/0 skipped и совпадение всех 64 source files; skipped не засчитаны |
| RV-06 | P1 | Исправлен | [Bounded recovery patch](../../patches/ner-window-recovery.patch), [NER-разбор](../operations-ner-windowing/README.md), [полный Requests](../operations-dependencies/public-requests.json): 119 analyzed/13 unsupported/0 errors; fail-closed не ослаблен |
| DEP-02 | P2 | Исправлен | Чистая установка closure, duplicate normalized names отклоняются; [installed inventory](../operations-dependencies/final-inventory.json) и равенство runtime probe закреплённому lock |
| DEP-01 | P1 | Обновления выполнены; остаточный риск принят | 42 known-fixed native records и прежние PyPI matches устранены в кандидате; четыре остаточных native-риска [явно приняты владельцем для закрытого контура](../operations-dependencies/risk-acceptance.md), `fixed_in_candidate=false` сохранён |
| DOC-03 | P3 | Исправлен в этапе 5 | В `e5e3115` review table ещё ожидала walkthrough, findings описывал RV-06 как текущий отказ, dev guide называл 144 tests последним набором. Статусы и ссылки обновлены; исторические observations не переписаны |

## Проверенные границы доверия

| Граница | Итоговое чтение кода | Подтверждение и предел |
| --- | --- | --- |
| Недоверенный Git/config/refs | [git_repository.py](../../src/ru_llm_scanner/git_repository.py), [git_plan.py](../../src/ru_llm_scanner/git_plan.py) | Отдельный metadata-view, фиксированные argv/env, raw object OID, no lazy fetch/replace/hooks/filters; [41 Linux Git tests](../operations-dependencies/git-linux.json). Object store должен быть неизменным во время scan |
| Обязательный анализ полного текста | [pipeline.py](../../src/ru_llm_scanner/pipeline.py), [engine.py](../../src/ru_llm_scanner/engine.py), NER patch | Ошибка обязательного слоя не становится пустым успешным результатом; [parity/quality](../operations-dependencies/scan-verification.json), [отмена/восстановление](../operations-dependencies/cancellation.json). Не универсальная гарантия полноты детекторов |
| Наследование baseline | [baseline.py](../../src/ru_llm_scanner/baseline.py), pipeline | Проверяются kind/schema/clean/manifest/tree/profile; [acceptance 16](../operations-dependencies/acceptance-verification.json) и новый negative control. Происхождение baseline обеспечивает доверенный процесс, цифровой подписи нет |
| Полные отчёты и безопасная консоль | [output.py](../../src/ru_llm_scanner/output.py), [html_report.py](../../src/ru_llm_scanner/html_report.py), CLI/launcher/Jenkins adapter | Escaped text/CSP, без внешних assets, private output, bounded diagnostics; новый control и прежние extras/browser. JSON/HTML атомарны по отдельности; process code 2 запрещает продвижение baseline |
| Контейнеры и offline | [docker_scanner.py](../../scripts/docker_scanner.py) | Immutable IDs/pull never, internal network, RO/non-root/cap-drop/no socket/no logging, свой exact project cleanup; [25 Compose](../operations-dependencies/docker-verification.json), [2 faults](../operations-dependencies/fault-verification.json), новый control. Host/Docker operator доверенный |

Итоговое чтение кода и контроль не обнаружили новых P0/P1 в этих границах.
Полный native call graph и эксплуатация каждого CVE не заявляются. Это
ограниченный результат ревью, не доказательство отсутствия всех уязвимостей.
Новых продуктовых изменений в этапе 5 не потребовалось.
