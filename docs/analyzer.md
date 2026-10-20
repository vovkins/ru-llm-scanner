# Analyzer: API и проверки разработчика

Полная последовательность подготовки/build/seal/engine/scanner находится в
[руководстве администратора](admin/build.md). Здесь детали адаптера и отдельных
проверок; обычный пользователь работает с [готовыми контейнерами](user/README.md).

## Контекст, runtime и модель

[Source lock](../upstream.lock.json) закрепляет tracked export-list, upstream SHA,
model manifest, патчи before/after, constraints и spaCy tree. `prepare` экспортирует
только разрешённые Git bytes, строго применяет patch и создаёт manifest. `verify-context`
отвергает changed/extra/symlink inputs. Host source не равен содержимому рабочей папки proxy.

`build` использует профиль/constraints; `seal` проверяет фактические model files,
packages, sources, spaCy/settings и image identity без внешней сети. Измеренный lock
прошлой CPU ARM64 сборки лежит в [locks](../locks/analyzer-cpu-linux-arm64.runtime.lock.json),
но fresh image требует собственного seal. [Reference/platform IDs и доверие](reference/artifacts.md).
Модель/каталог/HTTP-поля — в [справочнике](reference/detection.md).

## Raw/patched parity

Предполагаются готовый curated context, sealed image и **его** runtime lock.
Задайте пути к одному комплекту, output должен отсутствовать:

```sh
ANALYZER_CONTEXT=/trusted/build/analyzer
RUNTIME_LOCK=/trusted/build/analyzer.runtime.lock.json
.venv/bin/python scripts/check_analyzer_integration.py \
  --context "$ANALYZER_CONTEXT" --runtime-lock "$RUNTIME_LOCK" \
  --output-dir .build/analyzer-parity-new
```

В одной среде поочерёдно запускаются исходный и patched серверы. Проверяются
77 случаев NER, категории/интервалы/значения/score (absolute tolerance `1e-7`),
quality gates закреплённого корпуса, длинный текст, Unicode, 4 dictionary cases,
отказ непатченного API/неверной подписи/остановленного сервиса/модели/checksum.
Отказ обязательной NER не допускает успешного regex-only fallback.

Команды `check_analyzer_integration.py` и `check_rehearsal_parity.py` используют
общий helper: actual immutable image IDs до run, non-root host UID/GID, pull never,
network none/read-only root/input, cap-drop ALL/no-new-privileges, отдельный tmpfs.
Монтируются только allowlisted context, scanner `.py`/`.json` и тест; `.git`, `.env`,
посторонние `.build` и пользовательские reports недоступны. Имя/ownership label
уникальны, finally удаляет только собственные контейнеры.

Проверка sysfs требует только loopback в состоянии UP: неактивные tunnel interfaces
сами по себе не доказывают внешний маршрут. Сохраняются private log и безопасный
`offline-verification.json` с hashes/метриками без исходных значений.
NER parity и качество этого корпуса не заменяют [независимый code-v1](../verification/README.md).

## Upstream subset и синтетические NER-регрессии

Для prepared context того же source/profile:

```sh
.venv/bin/python scripts/analyzer.py build --context "$ANALYZER_CONTEXT" \
  --tag ru-llm-scanner-analyzer:upstream-tests --test-image
.venv/bin/python scripts/check_upstream_tests.py --context "$ANALYZER_CONTEXT" \
  --image ru-llm-scanner-analyzer:upstream-tests \
  --output .build/upstream-tests-new.json
.venv/bin/python scripts/check_upstream_tests.py --context "$ANALYZER_CONTEXT" \
  --image ru-llm-scanner-analyzer:upstream-tests --suite ner \
  --output .build/ner-regressions-new.json
```

В текущей offline CPU recipe test-image наследует sealed runtime с моделью,
но эти synthetic tests не выполняют inference настоящей модели. Полный набор tests/corpus
монтируется read-only; содержимое corpus не исполняется. Проверяются rules,
credentials, encoded values, merging, windows и NLP-контракт. Assertion logs
могут содержать синтетические значения и остаются локальными; отчёт содержит
counts/versions/provenance. Unit и prepared assets — [отдельная группа](development.md#группы-проверок-и-assets-test-01).

## Python API адаптера

```python
from pathlib import Path
from ru_llm_scanner.analyzer import AnalyzerClient, ExpectedAnalyzer

expected = ExpectedAnalyzer.from_runtime_lock(
    Path('/trusted/build/analyzer.runtime.lock.json'), Path('upstream.lock.json')
)

async def detect(text):
    async with AnalyzerClient('http://analyzer:5001', expected) as client:
        return await client.analyze(text)
```

Пример не запускает сервис: `analyzer` должен быть доступен во внутренней сети.
Адаптер отключает environment proxies/redirects, ограничивает параллельность/ответ,
не повторяет анализ. Async deadline охватывает slot/health/analyze/проверки после
ответа, включая медленное поступление chunks. `Detection.value` не входит в repr,
ошибки содержат только bounded code.

`DictionaryDetector.from_context(path)` загружает проверенные policy/rules и
возвращает отдельные `DICTIONARY_TERM` с исходными смещениями без замены текста.
Invalid rules отвергаются. Для общей обработки файлов — [Scan API](scan-api.md).

## Платформы и диагностика

CPU Linux ARM64 build/seal/real model подтверждены [evidence](../verification/README.md).
GPU targets сохранены в upstream; GPU inference/runtime и AMD64 не проверены.
Нужны отдельные base/constraints/spaCy pins/lock и действительная приёмка;
ARM64 CPU lock не переносится на CUDA. Скрытого GPU→CPU fallback нет.

`Prepared context changed` — новая подготовка в новой папке, не ручная правка
manifest. Package/spaCy mismatch — сверка mirrors и pins, не ослабление constraints.
`analyzer_profile_mismatch` — runtime/model/settings; `analyzer_contract_error` —
API patch/формат. Missing/corrupt model даёт отказ; ready/warmed-up обязательны.
[Обновление/откат](admin/updating-analyzer.md), [типовые ошибки](reference/errors.md).
