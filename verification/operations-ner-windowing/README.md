# RV-06: восстановление сущности на границе NER-окон

Исправление согласовано в [#26](https://github.com/vovkins/ru-llm-scanner/issues/26).
Исходная ревизия scanner — `6d2cdbf32ef7f11877ee9e85ff7ac35f9c75bbfb`.
Это проверка отдельного кандидата, а не изменение штатного deployment.
Полный Requests и согласованные runtime-проверки координируются с #24; результат
здесь не означает завершение #26 или итоговой приёмки #25.

## Причина и изменение

В полном `AUTHORS.rst` закреплённого Requests модель выдала граничную сущность,
которую единственное центрированное recovery-окно не подтвердило. Изменение
контекста меняет logits; отсутствие предсказания в одном дополнительном окне
не доказывает отсутствие исходной сущности. Прежний merge корректно завершал
такой запрос `window_boundary_unresolved`, но других контекстов не пробовал.

[Точный patch](../../patches/ner-window-recovery.patch) после отказа прежнего
центрированного recovery пробует два сдвига — четверть и три четверти окна.
Если граница всё ещё не подтверждена, последним шагом пробуются четыре нечётных
восьмых окна. Каждый следующий шаг запускается только после отказа предыдущего.
Дополнительное окно должно целиком вмещать незакрытый span; учитываются только
подтверждения той же категории, перекрывающие исходный кандидат и находящиеся
внутри окна. Остальные предсказания recovery не добавляются в результат.
Первоначальные кандидаты сохраняются. Если подтверждения нет, span длиннее
доступного контекста или inference отказал, остаётся ошибка, а не clean.
Успешный прежний путь дополнительных окон не запускает.

Upstream/proxy не изменён. Модель, tokenizer artifacts, словарь, пороги,
категории и frozen corpus сохранены. До/после hashes указаны в source lock.
Новая подпись профиля требует нового snapshot/baseline; исторический source lock
сохранён рядом со штатным runtime как
`locks/analyzer-cpu-linux-arm64.source.lock.json`.

## Выполненные проверки

| Проверка | Результат |
| --- | --- |
| Собственные unit/CLI | [145 passed, 0 skipped](unit-tests.json) |
| Upstream subset | [478 passed](upstream-tests.json) |
| NER unit и новые регрессии | [91 passed](ner-regressions.json), включая отсутствие подтверждения и отказ inference |
| Настоящая модель, API parity | [77 NER / 4 dictionary](offline-verification.json) |
| Независимый code-v1 | [46 direct parity, TP 33 / FP 13 / FN 4](scan-verification.json) |
| Полный AUTHORS, HTTP | [200 за 11.043 s](authors-http.json), прежний образ давал 503 |

Raw/patched parity сравнивает исходный и расширенный HTTP API **с одинаковым
исправленным NER**. Это не побитовое сравнение logits старой и новой реализации.
Независимые code-v1 показатели не изменились; публичный AUTHORS не размечен и
не используется для precision/recall. Его текст/находки не публикуются.

## Воспроизведение и границы

Новый source context готовится обычным `scripts/analyzer.py prepare` в отдельный
каталог. Для test image этого же контекста:

```sh
python scripts/check_upstream_tests.py --context "$CONTEXT" --image "$TEST_IMAGE" \
  --suite core --output .build/rv06-next/upstream-tests.json
python scripts/check_upstream_tests.py --context "$CONTEXT" --image "$TEST_IMAGE" \
  --suite ner --output .build/rv06-next/ner-regressions.json
python scripts/check_analyzer_integration.py --context "$CONTEXT" \
  --runtime-lock "$RUNTIME" --output-dir .build/rv06-next/parity
```

Синтетические регрессии находятся в `tests/integration/ner_window_cases.py`.
Дополнительный шаг воспроизведён на полном `tests/test_requests.py` того же
Requests commit: 106660 bytes, SHA-256
`4508b22c1aa65417427fe7e51ea1f4e3a3d43d3021acdeb5a5260720a1b367a1`.
Обе границы коротких PASSWORD spans требуют более мелкого сдвига контекста;
модель/пороги и исходные кандидаты сохраняются.
Исходный публичный input воспроизводится только как Git blob из commit
`b25c87d7cb8d6a18a37fa12442b5f883f9e41741`, путь `AUTHORS.rst`, 8037 bytes,
SHA-256 `67b09ec1002aef944fec0a4c6ab76d5662e0f596f289e1c7b280c24cbb749678`.
Проверяемый код репозитория не выполняется.

Для изоляции изменения NER диагностические образы построены слоями поверх
прежних локальных образов. Analyzer заменяет только NER source, source lock и
вычисленный provenance; scanner — четыре проверенных engine assets. Seal
проверяет реальные установленные sources/packages/model/dictionary. Dev test
image использует прежние библиотеки и монтирует новый проверенный context.
Это **не fresh build** зависимостей. Полная чистая сборка и advisory disposition
выполняются отдельно в [#24](https://github.com/vovkins/ru-llm-scanner/issues/24).

На HTTP-проверке: network none, read-only, non-root, drop ALL,
no-new-privileges, log driver none, 2 CPU / 2 GiB RAM. Времена зависят от стенда.
Один успешный AUTHORS не подтверждает обработку любого SVG/длинного текста.
Прежние images и default deployment сохранены, публикации/merge нет.
