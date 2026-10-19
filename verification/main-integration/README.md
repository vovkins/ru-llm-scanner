# Слияние семи этапов и проверка main

Пользователь явно согласовал слияние 2026-10-19, с отдельным ограничением:
релиз и образы не публиковать. Все семь PR последовательно слиты в `main`
merge-коммитами. Перед каждым слиянием проверен точный head SHA; следующий
PR перенаправлялся на `main` после подтверждения предыдущего слияния.
Исходные ветки сохранены, настройки GitHub/Jenkins не менялись.

## История интеграции

| Этап | PR | Исходный head | Merge-коммит в main |
| --- | --- | --- | --- |
| 1 | [#4](https://github.com/vovkins/ru-llm-scanner/pull/4) | `1e8e874` | `df164367cc3acb5c5ee5eb42f221d0d93dfacac4` |
| 2 | [#6](https://github.com/vovkins/ru-llm-scanner/pull/6) | `776cfa4` | `b035110121913703c7b3f8d5cf99d5d0c7f6eed2` |
| 3 | [#8](https://github.com/vovkins/ru-llm-scanner/pull/8) | `da315b2` | `bae36dad4e5003b55f0c6a2183e86b830f7bb820` |
| 4 | [#10](https://github.com/vovkins/ru-llm-scanner/pull/10) | `0c8dfa7` | `49d55a4d12ad08087c29a9d35c26da3d122ab72b` |
| 5 | [#12](https://github.com/vovkins/ru-llm-scanner/pull/12) | `e632ad0` | `9f7165f8b554878ba0a93413f72d398e74b64e6a` |
| 6 | [#14](https://github.com/vovkins/ru-llm-scanner/pull/14) | `b8e0625` | `2b31971ad94f2b5091c08afc568042e951cd1e27` |
| 7 | [#15](https://github.com/vovkins/ru-llm-scanner/pull/15) | `33dcad2` | `4d958e12070569c659e27f16ab118a35055e8d53` |

Первый родитель каждого merge-коммита — предыдущий `main`, второй — точный
head соответствующего этапа. Все семь heads являются предками итогового
`main`. [Полные SHA и время слияний](merges.json).

Дерево `main` после седьмого слияния (`4d958e1`) полностью совпало с подготовленным
этапом 7 (`33dcad2`): `c756f38d0bf838ba89ab82c48908792faa035126`.
После этого изменена только документация и добавлены результаты проверок;
продуктовый код, schema, профиль, модель, corpus и штатные locks сохранены.

## Повторные проверки

Проверки выполнены на слитом `main`, с готовыми локальными образами, на той же
среде CPU Linux ARM64/Docker Desktop, что и [приёмка этапа 7](../stage-7/README.md).
GitHub checks для этих PR отсутствуют; локальные свидетельства не выдаются за GitHub CI.

| Свидетельство | Результат |
| --- | --- |
| [Unit](unit-tests.json) | 131 тест, 0 failures/errors/skipped; хеши проверенного кода сохранены |
| [Production acceptance](acceptance-verification.json) | 16 запусков snapshot/diff/baseline, контекст/merge/history/кодировки/hostile repo; входы неизменны |
| [Offline CLI](cli-verification.json) | 9 сценариев; установленный wheel соответствует исходникам/schema, сеть только loopback |
| [Code-v1](scan-verification.json) | 46/46 direct parity; независимые TP 33 / FP 13 / FN 4, precision 71.74%, recall 89.19% |
| [Итоговая сверка](completion-checks.json) | 11 примеров / 22 отклонённых случая / 319 ссылок; Black 66 файлов, diff check; locks/IDs/proxy/cleanup |

Семь чужих работающих контейнеров сохранены без перезапуска. Собственных временных
контейнеров/сетей не осталось; исходный proxy и штатные артефакты не изменены.
Известные пропуски и ложные срабатывания code-v1 совпали с приёмкой этапа 7;
модель, правила и разметка не корректировались ради результата.

Команды из корня проекта, с установленными dev dependencies и подготовленным
`.build/analyzer`:

```bash
.venv/bin/python scripts/check_cli_tests.py --output-dir .build/main-integration/unit-tests
.venv/bin/python scripts/check_acceptance.py \
  --deployment-lock locks/scanner-cpu-linux-arm64.deployment.json \
  --output-dir .build/main-integration/acceptance
.venv/bin/python scripts/check_cli_integration.py \
  --context .build/analyzer \
  --runtime-lock locks/analyzer-cpu-linux-arm64.runtime.lock.json \
  --scanner-image ru-llm-scanner:stage6-cpu \
  --output-dir .build/main-integration/real-model
.venv/bin/python scripts/docker_scanner.py verify
.venv/bin/python scripts/check_contracts.py
.venv/bin/python -m black --check src tests docker scripts examples/jenkins \
  --extend-exclude 'check_contracts\.py'
git diff --check
```

Для повторного запуска используйте новые output-каталоги. Фактический host
интерпретатор этого прогона — `/private/tmp/ru-llm-scanner-spec-venv/bin/python`.
Значения и контекст остаются в локальных приватных отчётах; здесь сохраняются
только безопасные hashes/counts/версии. Старые JSON-свидетельства этапов не изменяются.

## Границы

Версия остаётся `0.1.0.dev0`. Релиз, теги и публикация образов не выполнялись;
сборка образов для этого слияния не требовалась. Историческое обновление/откат,
raw/patched parity и upstream regression подтверждены на этапе 7 и не повторяются
для неизменённого механизма. Визуальная QA HTML остаётся результатом этапа 5,
renderer не менялся.

Реальный Jenkins, GPU/AMD64, Linux-host UID mapping, корпоративный PKI и другой
физический offline host не проверены. Независимое качество детекторов и известные
FN/FP сохраняются; нулевой результат не даёт гарантии полноты. SHA-256 не подпись
происхождения, очередь не ограничивает всю RAM, CPU join не жёсткий deadline,
JSON/HTML атомарны по отдельности, SIGKILL/daemon loss может требовать cleanup.
Лицензия scanner и приватный канал сообщений об уязвимостях остаются решениями владельца.
