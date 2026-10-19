# Внутренний API сканирования

Этап 4 соединяет Git/text API, закреплённый Analyzer и словарь. Работает
Python API для snapshot/diff; пользовательские команды, JSON/HTML writer и
baseline подключаются на этапе 5. Это руководство для разработки и проверки,
не инструкция production-развёртывания.

## Подготовка и вызов

Нужны Python 3.11+, Git, установленный пакет и доверенные артефакты
[Analyzer](analyzer.md): подготовленный `.build/analyzer`, source lock,
runtime lock измеренного образа и соответствующий запущенный Analyzer.
Модель при вызове API не скачивается. Адрес ниже должен быть доступен из
окружения вызывающего процесса и указывать на закреплённый сервис.

```python
import asyncio
from pathlib import Path

from ru_llm_scanner.configuration import configuration_from_mapping
from ru_llm_scanner.engine import ScanEngine
from ru_llm_scanner.pipeline import scan_repository

engine = ScanEngine.from_context(
    Path(".build/analyzer"),
    Path("locks/analyzer-cpu-linux-arm64.runtime.lock.json"),
)
config = configuration_from_mapping(parameters={
    "analyzer_url": "http://analyzer:5001",
    "concurrency": 1,
    "context_lines": 2,
})
result = asyncio.run(scan_repository(
    Path("/repo"), engine, mode="snapshot", commit="HEAD", config=config,
))
print(result.summary())  # Без значений, контекста и текстов файлов.
```

Для перехода передайте `mode="diff", from_commit="COMMIT_A",
to_commit="COMMIT_B"` вместо `commit`. Комбинации аргументов проверяются.
Ревизии фиксируются в полные OID; checkout/fetch не выполняются. Подробные
ограничения клонов, refs, scope и кодировок — в [Git reader](git-reader.md).

`load_configuration(Path("/trusted/scanner.json"), parameters={...})` читает
явный строгий JSON; `configuration_from_mapping` принимает доверенный dict.
Частичные секции допустимы с обязательным `config_version="1.0.0"` для
переданного JSON. Явные параметры заменяют отдельные поля, списки целиком.
`EffectiveConfig()` создаёт defaults. Все варианты используют одни валидаторы;
scanner не ищет настройки в проверяемом репозитории или окружении.
[Полный формат и ограничения](configuration.md).

`ScanEngine.from_context` проверяет подготовленный контекст. Для отдельной
упаковки assets доступен `ScanEngine.from_artifacts(source_lock=...,
runtime_lock=..., policy_file=..., rules_file=...)`: проверяются locks и хеши
обеих словарных частей. Он не требует копировать серверные модули Analyzer
в scanner. Идентификатор образа берётся из измеренного runtime lock;
HTTP-подпись/каталог/модель проверяются при работе. Lock должен поступать из
доверенного процесса: HTTP и JSON сами по себе не доказывают подлинность образа.

## Что возвращается

`ScanResult` содержит `plan`, `configuration`, `engine`, `files` и `errors`.
`plan=None` означает, что полный манифест получить не удалось или preflight
не завершился. У плана есть target/base и отдельные `deleted` записи.
`files` охватывает все недиректориальные записи B в порядке сырых байтов пути.

| Поле/свойство | Смысл |
| --- | --- |
| `ScanFile.selection` | Git entry: raw/display path, OID/mode и тип изменения |
| `ScanFile.status`, `reason` | analyzed/unverified/excluded/unsupported/error и машинная причина |
| `size_bytes`, `encoding` | Фактически установленный размер/кодировка либо `None` |
| `ScanFile.findings` | Проверенные находки успешно завершённого файла |
| `result.findings` | Все находки в порядке путь/смещения/категория/source/rule |
| `result.errors` | Только безопасные code/stage/file_id, без оригинальных исключений |
| `manifest_sha256` | Хеш полного манифеста; `None` при незавершённом перечислении |
| `summary()` | Счётчики, complete/enumeration_complete, status/assurance/exit_code |

`Finding` содержит полный `value`, `context.text`, category/source/rule/score,
commit B, file ID, raw path в base64, стабильный finding ID, offsets и
координаты. `value == text[start_offset:end_offset]` проверяется до принятия
файла. Повторы по разным местам/источникам сохраняются; одинаковый ID
дедуплицируется с максимальным score. Категории и источники расширяемы.
[Правила ID и сортировки](reports.md).

Offsets считаются в Unicode code points декодированного исходного текста без
BOM. Строки/столбцы с 1, конец исключающий; CRLF — один разделитель, CR/LF
также разделители. Unicode/whitespace не нормализуются. Контекст включает
полные строки реально занятых символов `[start,end)`, затем padding соседей;
если конец указывает на начало новой строки, она не добавляется только из-за
исключающего end. Исходные переводы строк сохранены, включая многострочные
значения и EOF. Промежуточная позиция внутри CRLF остаётся точным code-point
offset и относится к предыдущей строке.

`repr` находок/результата не показывает value/context. Сами объекты содержат
их полностью: не печатайте `vars`, `dataclasses.asdict`, HTTP responses и
локальные traceback с дампом переменных. Публикуемые dev evidence не содержат
исходных значений; будущие пользовательские отчёты будут их содержать.

## Полнота и ошибки

Readiness проверяется до Git, даже для пустого дерева, A=B и отсутствия
выбранных файлов. Подпись проверяется около каждого анализа и в конце запуска.
Исходный полный текст передаётся в оба слоя; никаких маскирующих замен или
анализа только добавленных строк. Длинный текст использует окна upstream.

`analyzed` присваивается после Analyzer, словаря и проверки координат.
Результат файла атомарен: при сбое обязательного слоя его незавершённые
кандидаты не публикуются; находки других завершённых файлов сохраняются.
Смена подписи останавливает новые анализы, делает запуск неполным; уже
отправленные параллельные запросы также проходят проверку подписи.

| Итог | Код | Assurance |
| --- | --- | --- |
| Завершённый snapshot, нет/есть находки | 0/1 | snapshot_verified |
| Завершённый diff без baseline, нет/есть находки | 0/1 | changed_files_only |
| Ошибка файла или финальной проверки | 2, incomplete | none |
| Ошибка до полного плана/preflight | 2, error | none |

`complete` означает завершение заданной поддерживаемой текстовой обработки,
а не отсутствие секретов во всех объектах. Excluded/unsupported перечисляются
явно и не становятся обработанными. Неизменённые файлы diff имеют
`unverified/no_baseline`; даже A=B не подтверждает весь B. На этом этапе нет
`inherited` и `baseline_verified`. Приоритет 2 → 1 → 0, включая частичные находки.

Ошибки config/artifact/аргументов до запуска могут быть исключениями
`ConfigError`/`AnalysisError` с безопасным кодом. Операционные ошибки внутри
запуска превращаются в `ScanError`; отмена распространяется как
`asyncio.CancelledError` после очистки. `summary()` — dev API, не сериализованный
`scan_report` и не доказательство baseline. Writer/semantic validator — этап 5.

## Нагрузка и завершение

При concurrency `c` работают `c` HTTP workers и очередь длины `c`. Producer
держит ещё один подготовленный элемент: до `2c+1` полных текстов могут
одновременно ожидать/проходить анализ. Git reader принадлежит одному отдельному
потоку; словарь и координаты обрабатываются в CPU pool до `c` потоков.
Манифест, готовые находки и их полный контекст хранятся в памяти до возврата;
очередь не ограничивает их суммарный размер и внутреннюю память модели/JSON.
`max_file_bytes` ограничивает один blob, а не RAM всего процесса. Line index
также требует память пропорционально числу строк обрабатываемого текста.

Дедлайны Git сохранены; analyze timeout охватывает HTTP, словарь и координаты
одного файла. Readiness имеет отдельный overall deadline. Автоматических
повторов анализа нет; только начальная readiness допускает ограниченное
ожидание/повторы health. Новый запуск после ошибки выполняется явно.

Отмена закрывает клиент, Git и worker-задачи. Уже выполняющуюся синхронную
операцию Python нельзя безопасно принудительно остановить: pipeline дожидается
её окончания, затем отвергает поздний успех. Поэтому возврат после timeout/
отмены может быть позже дедлайна; фоновых scanner-потоков после возврата нет.
Закрытие HTTP не гарантирует остановку вычислений внутри удалённого Analyzer:
управление процессом контейнера относится к оператору/этапу 6.

На доступном CPU ARM64 стенде создание синтетического Git-репозитория и
snapshot 46 небольших файлов, включая ожидание readiness, заняли около
8.2 секунды. Это не SLA для 10 MiB, произвольных
репозиториев или concurrency>1. GPU/другие архитектуры не проверены.

## Воспроизводимая offline-проверка

Сначала подготовьте и seal CPU-образ по [Analyzer](analyzer.md).
Dev-образ ниже содержит только Python/Git/HTTPX, без модели. Сборка требует
источники зависимостей; build context включает только Dockerfile.

```bash
mkdir -p .build/stage-4/image-context
cp docker/scan-test.Dockerfile .build/stage-4/image-context/Dockerfile
docker build --platform linux/arm64 -t ru-llm-scanner-scan-tests:stage4 \
  .build/stage-4/image-context
.venv/bin/python scripts/check_scan_integration.py \
  --runtime-lock locks/analyzer-cpu-linux-arm64.runtime.lock.json \
  --context .build/analyzer --scanner-image ru-llm-scanner-scan-tests:stage4 \
  --output-dir .build/stage-4/real-model
```

Launcher проверяет фактический platform Image ID Analyzer и хеши словаря,
запускает собственный временный Analyzer с `--network none`; scanner разделяет
только его сетевое пространство, общается по loopback. Снаружи маршрута нет.
Scanner работает от UID 65534, read-only FS, без capabilities; получает только
явный список исходников/синтетических fixtures/locks/словарных assets read-only.
Рабочий репозиторий, `.git`, secrets и конфиги пользователя не монтируются.
Собственный Analyzer останавливается в `finally`; существующие сервисы не нужны.
Это dev-harness для проверенного ARM64 runtime, не штатная упаковка scanner.

Проверка сопоставляет pipeline с прямым Analyzer+словарём на всех файлах,
независимо проверяет координаты, full-file diff, ошибки и профиль. Отдельно
измеряет качество по [разметке code-v1](../tests/corpus/README.md), не требуя
фиктивных 100%. Результат содержит версии/хеши и ошибки категорий/границ без
значений. Фактические метрики и пропуски — в
[результатах этапа 4](../verification/stage-4/README.md).
