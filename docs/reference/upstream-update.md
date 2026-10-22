# Подготовка обновления ru-llm-proxy

Это инструмент **сопровождающего**, а не дополнительный шаг пользователя.
Обычный путь остаётся `make build/test/scan/diff`. Подготовка кандидата не меняет
текущий `upstream.lock.json`, `.build/workflow/current`, модель, словарь,
зависимости или baseline. Новые исходники ещё не означают принятый engine.

Нужны только `python3` 3.11+ и Git; используйте доверенный checkout scanner.
Команда `python3 -I -S` из примеров изолирует импорт от окружения и входного клона.
Никаких Docker, venv, модели или сети для compare/prepare не требуется.
Самодостаточный локальный клон proxy уже должен содержать оба точных SHA;
инструмент не делает fetch, checkout и не выполняет его код/hooks/filters.
Рабочие `.env`, configs и secrets не читаются. Tracked Git-объекты читаются
через тот же изолированный [Git reader](../git-reader.md), что в scanner.

## 1. Сравнить ревизии

Путь PROXY замените своим. Сборочные системные предпосылки готовятся отдельно;
`.build` — собственный рабочий parent, конечный output должен быть новым:

```sh
umask 077
mkdir -p .build
PROXY="$HOME/git/ru-llm-proxy"
A=da4f50a87ddf8a6c160c5f1893f5bf526f713d1c
B=9e47e6594ba3d9616ba90720994ced008335416c
python3 -I -S scripts/update_upstream.py compare \
  --source "$PROXY" --from "$A" --to "$B" \
  --output .build/upstream-comparison
```

Сравнение охватывает **всё дерево**, включая файлы вне прежнего export-list.
Создаются `comparison.json`, краткий `comparison.md` и `review-template.json`.
Без решений сопровождающего ожидается **код 2 / status blocked**; при `set -e`
обработайте его явно и откройте приватный результат. Это не находка scanner.

| Код инструмента | Значение |
| --- | --- |
| `0` | Сравнение reviewed либо кандидат source_prepared |
| `2` | Есть blockers либо ошибка входа/подготовки |

Изменения содержат path/previous_path, A/D/M/R, mode/OID/SHA-256 до и после,
группу, disposition и reason. Rename определяется только для однозначного
совпадения содержимого; изменённый rename остаётся честным delete/add.
Raw Git stderr, исходный код и значения конфигураций в console не печатаются.
Выводимые пути JSON-экранированы. Для автоматизации используйте код и JSON.

## 2. Проверить применимость и адаптацию

`review-template.json` — заготовка, не автоматическое одобрение. Сохраните
review в доверенном месте **вне proxy**. [Schema v1](../../schemas/upstream-update-v1.schema.json)
описывает review/comparison/candidate; неизвестные поля, duplicate JSON keys,
неверные типы и несовпадающие hashes/SHA отвергаются.

| Disposition | Решение |
| --- | --- |
| `export` | Перенести файл/изменение в candidate source inventory; для удаления убрать, для rename перенести имя |
| `adapter` | Изменение реализуется настройкой/обвязкой scanner, например вместо proxy Compose |
| `proxy_only` | Не переносить с явной reason: routing/gateway/history/CI/docs proxy |
| `decision` | Требуется решение; блокирует готовность |

Review привязан к **обоим полным SHA**, полному набору changed paths и хешам
каждого изменения. Старый review не подходит для произвольного нового main.
Существующий экспорт нельзя просто объявить proxy_only/adapter и молча заменить
непроверенными bytes. Новые зависимости/модель/build base/notices/лицензии
выделяются в blockers, даже если файл помечен export: их принятие требует
отдельного решения и обновления соответствующих pinned artifacts.

`extra_sources` перечисляет необходимые неизменённые файлы и reason.
AST-проверка видит локальные imports, включая lazy imports внутри функций,
проверяет их наличие в экспорте, а также существующие в Git буквальные
JSON/text resource paths. Она выполняется **после адаптационных patches**.
`resource_exclusions` требует явной reason для найденного ресурса вне экспорта.
Новые `PRESIDIO_ANALYZER_*` настройки получают явные значения в review.environment.

Это ограниченный статический анализ: динамические imports, вычисляемые пути,
доступность сторонних imports и фактический API им не доказываются.
`static_analysis_acknowledged=true` подтверждает понимание этих границ,
а не заменяет runtime/upstream/quality тесты. Report перечисляет ограничения.

Патчи проверяются по полному SHA-256, before/after targets и точным offsets/hunks.
Fuzz и автоматического rebase нет. Если upstream сдвинул/изменил target,
подготовьте reviewed replacement в `review.patches` с `replaces`, новым path,
hashes/targets и reason. Путь относителен к каталогу review и должен лежать в
`patches/`; старый patch в Git не перезаписывается.

Для согласованной пары A/B есть [проверенный review](../../examples/upstream/base64-review.json)
и [описание всех решений](../../examples/upstream/README.md). Он переносит девять
новых файлов, сохраняет словарь и включает **candidate-only**
`PRESIDIO_ANALYZER_BASE64_POLICY=logistic`. Upstream по умолчанию использует
`content`; сравнение обоих режимов и принятие logistic остаются отдельной
функциональной приёмкой этапа6. Текущий engine scanner не переключается.

## 3. Подготовить отдельный кандидат

После разбора review и конфликтов:

```sh
python3 -I -S scripts/update_upstream.py compare \
  --source "$PROXY" --from "$A" --to "$B" \
  --review examples/upstream/base64-review.json \
  --output .build/upstream-reviewed
python3 -I -S scripts/update_upstream.py prepare \
  --source "$PROXY" --from "$A" --to "$B" \
  --review examples/upstream/base64-review.json \
  --output .build/upstream-candidate
```

Для другой пары задайте собственный рассмотренный review. Новый output
создаётся с `0700`, файлы CLI — с `0600`; parent уже должен существовать.
Symlink/submodule/external Git metadata, output внутри proxy/действующего
workflow, непустой или уже существующий output не принимаются. Права чужих
каталогов не исправляются; raw logs/контексты не публикуйте автоматически.

`prepare` повторяет сравнение и создаёт только source materials:

| Путь внутри output | Назначение |
| --- | --- |
| `comparison.json`, `.md`, `review-template.json`, `review.json` | Решения, границы, blockers и предъявленный review (если задан) |
| `candidate/upstream.lock.json` | Новый pin/sources/patches/environment без замены текущего lock |
| `candidate/patches`, `locks`, `docker/probe_runtime.py` | Проверенные inputs существующей source preparation |
| `contexts/cpu-linux-amd64` и `contexts/cpu-linux-arm64` | Раздельные контексты и manifests выбранных платформ |
| `candidate.json` | Финальный source_prepared marker, hashes всех файлов/content и profiles |

Общий шаг `upstream.prepare_payloads` перепроверяет каждый payload по source lock
и использует прежнюю цепочку генерации/verify-context. Старый explicit prepare
использует этот же шаг. Это не второй build subsystem. Оба контекста проверяются
существующим `verify_context` до записи candidate.json.

Повтор с теми же inputs в другой новый output даёт тот же content manifest;
имя папки и время в него не включены. Отказ может оставить частичные private
материалы, но **не source_prepared marker**. Existing output не переиспользуется.
Marker связывает bytes, не удостоверяет доверенное происхождение чужого пакета.

При необходимости отдельно проверьте контекст:

```sh
python3 -I -S scripts/analyzer.py verify-context \
  --context .build/upstream-candidate/contexts/cpu-linux-amd64
```

## Параметры и типовые отказы

| Параметр | Правило |
| --- | --- |
| `--source` | Обязательный self-contained локальный proxy clone/bare |
| `--from`, `--to` | Обязательные полные SHA; from совпадает с pin исходного lock |
| `--source-lock` | Optional: текущий доверенный upstream.lock.json scanner |
| `--review` | Optional для compare, обязателен для prepare; вне входного proxy |
| `--output` | Новый private каталог с существующим parent; не текущая установка |

`unreviewed_change` — разобрать каждый файл; `missing_local_dependency` —
дополнить экспорт/обоснованный resource exclusion; `new_setting_needs_explicit_value`
— определить настройку кандидата; `patch_input_changed`/`patch_not_exact` —
предъявить reviewed exact patch. `foundation_change_requires_decision` требует
отдельной оценки model/dependencies/build/notices. `review_*_mismatch` означает
устаревшее или неполное решение; не исправляйте hashes ради формального pass.
Ошибки layout/output/types требуют исправить вход, без автоматического chmod/fetch.

## Что ещё не принято

`source_prepared` всегда имеет `accepted_into_installation=false` и
`runtime_acceptance_performed=false`. Tool не создаёт runtime/deployment locks,
не строит images, не обучает модель, не запускает upstream tests и не продвигает
baseline. Коэффициенты нового Base64 recognizer — часть reviewed source code;
NER artifacts и зависимости этим не обновляются.

Приёмка нового engine требует native AMD64/ARM64 build, upstream regressions,
паритет/независимое качество/длинный текст, baseline incompatibility, настоящий
Jenkins и обновление/откат по отдельному плану этапа6. Нужна также проверка
происхождения нового кода и notices перед распространением: source comparison
не является самостоятельным подтверждением условий стороннего кода.
[Обновление и откат](../admin/updating-analyzer.md), [план #47](https://github.com/vovkins/ru-llm-scanner/issues/47).
