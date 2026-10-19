# Подготовка и проверка Analyzer

На этапе 2 реализован механизм обнаружения. Эти команды собирают и проверяют
Analyzer. Команды `snapshot/diff`, отчёты и baseline доступны по
[dev quickstart CLI](cli-quickstart.md) и [штатному Docker quickstart](docker-quickstart.md).
Репетиция обновления/отката проверена на этапе 7: [инструкция](updating-analyzer.md).

## Окружение

Нужны Python 3.11+, Git и Docker с BuildKit и платформенным inspect (API 1.49+).
Проверено на macOS/Apple Silicon, Docker 29.6.1, Linux ARM64, CPU; host-инструменты
проверены на Python 3.12.14, образ использует Python 3.11.16.
В примерах `python3.11` можно заменить другим доступным Python 3.11+.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e . -r requirements-dev.txt
```

Для подготовки/сборки могут потребоваться сеть или внутренние зеркала.
Веса NER (около 709 MB) и библиотеки входят в готовый образ. Выходные данные
инструментов хранятся в `.build/`, исключённом из Git.

## Закрепление

[upstream.lock.json](../upstream.lock.json) — source lock v1: конкретный SHA
прокси, 97 SHA-256 файлов (Analyzer, синтетические тесты, словарь, notices),
модель/ревизия и хеши всех её файлов, патч и хеши до/после, build-профиль.
[Constraints CPU ARM64](../locks/requirements-cpu-linux-arm64.txt) закрепляют
71 фактически установленный пакет. Профиль также фиксирует дерево файлов spaCy.
Список версий не является утверждением о побайтово одинаковом image при любой
новой сборке: системные пакеты и метаданные сборки тоже влияют на результат.
Фактический образ проверяется отдельно, получает новый runtime lock и проверки.

Подготовка из локального клона читает объекты конкретного коммита:

```bash
.venv/bin/python scripts/analyzer.py prepare \
  --source ../ru-llm-proxy --output .build/analyzer --profile cpu-linux-arm64
.venv/bin/python scripts/analyzer.py verify-context --context .build/analyzer
```

Рабочие изменения, `.env` (даже закоммиченный вне export-list), secrets и
неперечисленные файлы не экспортируются. Патч применяется собственным строгим
разбором unified diff: без shell, fuzz, смещения или игнорирования хешей.
Папка назначения должна отсутствовать. Для обновления используйте новую папку,
а не удаляйте пользовательские каталоги автоматически.

Альтернатива — явное получение того же публичного SHA на этапе подготовки:

```bash
.venv/bin/python scripts/analyzer.py prepare \
  --fetch --output .build/analyzer-from-github --profile cpu-linux-arm64
```

`--source` и `--fetch` взаимоисключающие. Скачивание не выполняется при анализе.
Оба способа проверены и дали одинаковый подготовленный контекст.

## Сборка и runtime lock

```bash
.venv/bin/python scripts/analyzer.py build \
  --context .build/analyzer --tag ru-llm-scanner-analyzer:local-cpu
.venv/bin/python scripts/analyzer.py seal \
  --context .build/analyzer --image ru-llm-scanner-analyzer:local-cpu \
  --output .build/runtime-cpu.lock.json
```

Сборка использует закреплённый Dockerfile upstream и базовый digest Python,
добавляет constraints, словарь, notices, offline inventory probe и настройки
того же профиля прокси. CPU- и GPU-цели исходного Dockerfile сохранены.

`seal` проверяет метки build context, платформу, исходники, все модельные файлы,
spaCy, версии пакетов и настройки в контейнере с `--network none`. Сохраняются
реальные provenance/analysis signature и идентификаторы Docker, не заглушки.
Некорректный результат не записывается как финальный runtime lock.

Измеренный lock проверенного CPU ARM64 образа сохранён в
[locks](../locks/analyzer-cpu-linux-arm64.runtime.lock.json), результаты — в
[verification](../verification/stage-2/README.md). Это запись локальной сборки;
образ не опубликован, повторная сборка требует собственного `seal`.

В Docker 29/containerd ID обычного inspect может быть OCI index, а его
платформенный manifest не всегда принимается как локальная ссылка запуска.
Поэтому runtime lock хранит отдельно `image_id` для профиля, `image_id_kind`,
`image_descriptor` и `image_reference_id` для запуска с указанной платформой.
Нельзя подменять платформенный digest плавающим tag или общим index.
Получение платформенного состояния опирается на
[docker image inspect --platform](https://docs.docker.com/reference/cli/docker/image/inspect/).

Проверка lock без Docker: `load_runtime_lock(path, source_lock)`; она проверяет
структуру и согласованность, не удостоверяет подлинность произвольного образа.
Храните lock как доверенный артефакт сборки. Чужой JSON не становится доверенным
только после прохождения валидации.

## Корпоративная сеть и CA

`prepare --certs-dir /trusted/ca` явно копирует верхнеуровневые `*.crt` и
включает их хеши в prepared manifest. Символические ссылки не принимаются.
Соседняя локальная `certs/` автоматически не читается.

`build --build-arg NAME` передаёт значение из окружения Docker; можно также
явно задать `NAME=value`. Поддержаны `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`,
`PIP_INDEX_URL`, `PIP_TRUSTED_HOST`, `PIP_PROXY`, `PYTORCH_INDEX_URL`,
`PYTORCH_GPU_INDEX_URL`, `NER_MODEL_PROXY`. Поведение соответствует возможностям
сборки прокси. Не передавайте действующие ключи/пароли в build args: upstream
Docker/pip могут выводить параметры сборки в лог. Зеркала должны содержать
точные закреплённые версии; подмена версии ради успешной установки недопустима.

## Проверки с настоящей моделью

```bash
.venv/bin/python scripts/check_analyzer_integration.py \
  --context .build/analyzer --runtime-lock .build/runtime-cpu.lock.json \
  --output-dir .build/verification
```

Контейнер запускается read-only с `--network none`, отдельным tmpfs и папкой
результатов. В одной и той же среде последовательно запускаются исходный
сервер из закреплённых байтов и сервер с патчем. Проверяются все 77 случаев
корпуса NER, интервалы/значения/категории и score с абсолютным допуском `1e-7`,
исходные quality gates, длинный текст, Unicode и словарные совпадения.
Проверяются отказ API без патча, неверная подпись, остановленный сервис,
неполная модель и ошибочная контрольная сумма. Успешный regex-only fallback
при отказе обязательной NER не допускается. Внешние LLM не вызываются.

Docker kernel может создавать неактивные tunnel-интерфейсы и при network=none.
Проверка подтверждает только loopback в состоянии UP; остальные интерфейсы
не считаются доступным интернетом по одному присутствию в sysfs.

Отчёт `offline-verification.json` содержит метрики/идентификаторы случаев,
без исходных текстов и найденных значений. Это оценка корпуса upstream,
и не распространяет измеренное качество на любые произвольные исходники.
Отдельные метрики кода доступны в [code-v1](../verification/stage-7/README.md).

## Быстрые тесты upstream и адаптера

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_contracts.py
.venv/bin/python scripts/analyzer.py build --context .build/analyzer \
  --tag ru-llm-scanner-analyzer:local-tests --test-image
.venv/bin/python scripts/check_upstream_tests.py --context .build/analyzer \
  --image ru-llm-scanner-analyzer:local-tests \
  --output .build/verification/upstream-tests.json
```

Upstream test-image не содержит весов NER. В него read-only монтируется полный
закреплённый набор тестов и синтетический DKB-корпус, без исполнения команд
из файлов корпуса. Проверяются распознаватели, credentials, слияние,
кодированные значения, окна текста и NLP-контракт. Полный локальный лог
может содержать синтетические значения при падении assert; в машинном отчёте
только итог, версии пакетов, перечень тестов и provenance.

## Python API адаптера

```python
from pathlib import Path
from ru_llm_scanner.analyzer import AnalyzerClient, ExpectedAnalyzer

expected = ExpectedAnalyzer.from_runtime_lock(
    Path(".build/runtime-cpu.lock.json"), Path("upstream.lock.json")
)

async def detect(text):
    async with AnalyzerClient("http://analyzer:5001", expected) as client:
        return await client.analyze(text)
```

Пример показывает API, не запускает сам сервис: имя `analyzer` должно быть
доступно во внутренней сети [штатного Compose запуска](docker-quickstart.md).
Адаптер отключает environment proxies и
redirects, не повторяет анализ, ограничивает параллельность и размер ответа.
Общий дедлайн охватывает ожидание слота, health, анализ и проверку после него;
он действует и при медленно поступающих кусках ответа. [HTTPX timeout](https://www.python-httpx.org/advanced/timeouts/)
сам по себе ограничивает сетевую неактивность, поэтому дополнен asyncio deadline.
Значение `Detection.value` не входит в repr. Ошибки содержат только bounded code.

`DictionaryDetector.from_context(path)` использует проверенные policy/rules
upstream и возвращает отдельные `DICTIONARY_TERM` с исходными смещениями.
Замены не выполняются; неоднозначность восстановления чужого replacement
не имеет смысла для поиска. Невалидная конфигурация правил отклоняется.

## Платформы и диагностика

| Возможность | Статус |
| --- | --- |
| CPU Linux ARM64 | Сборка, seal, реальная модель и parity проверены |
| GPU Dockerfile и CUDA-политика upstream | Сохранены; GPU runtime lock не изготовлен |
| GPU inference | Не проверен: стенд Apple Silicon без CUDA |
| CPU Linux AMD64 и другие платформы | Нужны собственные constraints/base/spaCy pins и отдельный проверенный профиль |

Нельзя применять ARM64 base digest и CPU constraints к GPU. Для новой платформы
создаётся отдельный build profile с реальными артефактами и проверками.
Неподдержанный ключ профиля отклоняется, скрытого GPU→CPU fallback нет.

`Prepared context changed` — подготовьте заново в новой папке; не редактируйте
manifest вручную. `Installed runtime packages differ` / spaCy mismatch —
проверьте зеркало и constraints, не ослабляйте pinning. `analyzer_profile_mismatch`
— проверьте runtime lock/модель/настройки. `analyzer_contract_error` — проверьте
наличие патча и формат ответа. Модель должна достигнуть ready/warmed-up;
отсутствующие/повреждённые файлы дают отказ.
