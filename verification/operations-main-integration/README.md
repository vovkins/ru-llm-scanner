# Интеграция подготовки к эксплуатации в main

Пользователь явно согласовал слияние **2026-10-20 (MSK)**: PR #19/#21/#23/#27/#28/#29/#30,
проверку результата, обновление документации и задач. Релиз и публикация образов
не разрешены. Все семь PR последовательно слиты **merge-коммитами** в `main`.

## Подтверждение состава

| PR | Согласованный head | Merge-коммит в main |
| --- | --- | --- |
| [#19](https://github.com/vovkins/ru-llm-scanner/pull/19) | `fc0dcbfa4304` | `4c7968806e61f8703d3ffa7e79c0bbab01b1ba17` |
| [#21](https://github.com/vovkins/ru-llm-scanner/pull/21) | `5ff130aae8c1` | `f5ff292c811bd89849a9e5a8e64ae5b9bc52b355` |
| [#23](https://github.com/vovkins/ru-llm-scanner/pull/23) | `755152b8d658` | `4aea5d8b9b78c3f344441db60ef3cbb6ed164b48` |
| [#27](https://github.com/vovkins/ru-llm-scanner/pull/27) | `6d2cdbf32ef7` | `67260227a1635050dec72c094bb72c76020d466a` |
| [#28](https://github.com/vovkins/ru-llm-scanner/pull/28) | `5097ea5ff799` | `ccd96352eb872a2185a7782c914927959f5457f6` |
| [#29](https://github.com/vovkins/ru-llm-scanner/pull/29) | `e5e311504abc` | `729f2bb9e14024c95251b3c27d7b27cb76327081` |
| [#30](https://github.com/vovkins/ru-llm-scanner/pull/30) | `2e25402953d5` | `09abd6c6f0b5db08d36e624552e40cae4cf89500` |

Первый родитель каждого merge — предыдущий main, второй — точный согласованный
head. Перед следующим слиянием PR перенаправлялся на main, проверялись состав
patch и ожидаемое дерево. Ни force push, ни admin bypass, ни автоочередь не
использовались. Исходные ветки сохранены.
[Полные SHA, bases и время слияний](merges.json).

Исходный main: `336feb64b201b0e9b807059f3d60b50fdee41ebb`.
Checkpoint после семи слияний: **`09abd6c6f0b5db08d36e624552e40cae4cf89500`**.
Его дерево полностью совпало с принятым head #30 `2e25402953d51fe2a6f19e7defc185479ce020e8`:
`2381c8cf2ac902fafed391348ec241afd0fa05e8`. Все семь heads являются предками checkpoint.
[Проверка дерева и родителей](tree-verification.json).

После этого изменена только документация и добавлены безопасные результаты
интеграции. Runtime-код, зависимости, исходники/патчи детекторов, схема,
модель/словарь/corpus и параметры распознавания при слиянии не менялись.

## Новые проверки слитого main

| Проверка | Результат |
| --- | --- |
| [Полный unit](unit-tests.json) | **155 tests, 0 failures/errors/skipped**, 64 hashes проверенных исходников, неизменность входов suite |
| [Installed offline control](control-verification.json) | Verify 0 → чистый snapshot A 0 → strict diff A/B с синтетическим паролем 1 → неподходящий baseline 2/assurance none |
| [Документация](documentation.json) | Команды/help/defaults, shell syntax, навигация и соответствие synthetic demo; отдельное evidence без обещаний browser/walkthrough |
| [Итоговые статические проверки](completion-checks.json) | Contracts/schema/examples/links, Black, diff, hashes, допустимый состав doc changes |
| [Сохранность](preservation.json) | Штатные locks/images, предыдущий комплект для отката, proxy/model/corpus, семь чужих контейнеров и owned cleanup |

Новый control выполнен из отдельной минимальной установки с launcher из слитого
main, Python `-I -S` и явным deployment lock, без `src/`/dev venv/proxy внутри
установки. Использованы те же проверенные immutable images Linux ARM64, что и
[итоговая приёмка](../operations-stage-5/README.md). Проверены process/summary/report
codes, полный пароль/контекст/координаты/категория/источник/score в JSON/HTML,
`baseline_verified` для 1 analyzed/1 inherited, права 0700/0600, безопасная консоль,
неизменность input и cleanup точного project. Полные reports/raw logs приватны.

GitHub checks у этих PR отсутствуют. Эти локальные результаты не объявляются
GitHub CI. Изолированные unit HTTP fixtures не обращались к внешним моделям;
рабочий scan не скачивал зависимости/images и не выполнял код входного клона.

## Применимость предыдущих результатов

[Приёмка этапа 5](../operations-stage-5/README.md) установила соответствие 211 curated
inputs Analyzer, 67 scanner build inputs, 21 installed module/schema и полного
runtime probe закреплённому комплекту; [19 наборов evidence](../operations-stage-5/evidence-reuse.json)
связаны с конкретными входами/images. При интеграции доказано полное равенство
дерева принятому head, а source hashes нового unit также совпали.

Поэтому upstream 478 / NER regression 96 / 77 NER+4 dictionary / code-v1 46 direct
parity, Compose/faults/transfer/rollback/capacity, оба walkthrough и полный Requests
не повторялись для неизменных runtime-входов. Они остаются прежними прогонами;
новые unit/control выделены в таблице выше. Исторические JSON-протоколы этапов
не переписаны под новый commit.

Независимое качество code-v1 остаётся **TP33/FP13/FN4**, precision 71.74%, recall
89.19%; модель/пороги/разметка не корректировались. Requests:119 analyzed/13 unsupported/
0 errors/612 кандидатов, без ground truth или внешней проверки credentials.
[Матрица возможностей, платформ и ограничений](../operations-stage-5/readiness-matrix.md).

## Комплект и границы

Версия остаётся `0.1.0.dev0`. **Исторический default deployment сохранён**;
слияние исходников не заменяет установленные контейнеры и не принимает другой
комплект автоматически. Для локального пилота выбирайте явный deployment lock
проверенного комплекта: [candidate.deployment.json](../operations-dependencies/candidate.deployment.json),
либо lock собственной проверенной сборки по [admin build](../../docs/admin/build.md).
Четыре native-риска [приняты владельцем](../operations-dependencies/risk-acceptance.md)
для этого комплекта и закрытого контура; acceptance не распространяется
автоматически на другие images/окружения. Старые images остаются для отката.

Релиз, tags, registry, публикация/пересборка образов и внешние настройки
GitHub/Jenkins/PKI не выполнялись. Чужие проекты не останавливались и не
перезапускались; broad prune не применялся. Дальнейший запуск на целевом сервере,
лицензия scanner и приватный vulnerability contact — отдельные решения владельца.
AMD64/GPU, реальный Linux host/Jenkins controller и другой физический offline host
не объявлены проверенными.

## Повторить проверки

Нужны dev dependencies и подготовленный `.build/analyzer`; [предусловия full unit](../../docs/development.md).
Все output-каталоги ниже выбираются новыми:

```sh
.venv/bin/python scripts/check_cli_tests.py --output-dir .build/main-check-unit-new
.venv/bin/python scripts/check_contracts.py
.venv/bin/python scripts/check_documentation.py --output .build/main-check-docs-new.json
.venv/bin/python -m black --check src tests docker scripts examples/jenkins \
  docs/review/reproduce.py verification/operations-stage-2/prepare_context.py \
  --extend-exclude 'check_contracts\.py'
git diff --check
python3 scripts/docker_scanner.py verify \
  --deployment-lock verification/operations-dependencies/candidate.deployment.json
```

Для installed control следуйте [контрольному snapshot](../../docs/admin/installation.md#контрольный-snapshot)
и [strict diff A/B](../../docs/user/README.md#5-проверить-переход-a--b), используя
синтетический клон и собственные private outputs. Ожидаемый код 1 требует явной
обработки в shell/CI. Actual host interpreter нового прогона — Python 3.12.14;
проверенные images содержат CPython 3.11.17. Новой сборки для интеграции не требовалось.
