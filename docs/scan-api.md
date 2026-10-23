# Внутренний API сканирования

Python API соединяет Git/text, закреплённый Analyzer и словарь; CLI, JSON/HTML
и baseline используют тот же pipeline. [Dev quickstart](cli-quickstart.md). Это руководство для разработки,
не инструкция production-развёртывания.

## Подготовка и вызов

Нужны Python 3.11+, Git, установленный пакет и доверенные артефакты
[Analyzer](analyzer.md): подготовленный context, source lock,
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
    Path("/trusted/build/analyzer"),
    Path("/trusted/build/analyzer.runtime.lock.json"),
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
Для доверенного отчёта A передайте `baseline=Path("/trusted/report.json")`,
при строгом запуске также `require_baseline=True`. Отчёт проходит runtime
validation и сверяется с полным деревом A/профилем; отказ не включает fallback.
Ревизии фиксируются в полные OID; checkout/fetch не выполняются. Подробные
ограничения клонов, refs, scope и кодировок — в [Git reader](git-reader.md).

`load_configuration(Path("/trusted/scanner.json"), parameters={...})` читает
явный строгий JSON; `configuration_from_mapping` принимает доверенный dict.
Частичные секции допустимы с обязательным `config_version="1.0.0"` для
переданного JSON. Явные параметры заменяют отдельные поля, списки целиком.
`EffectiveConfig()` создаёт defaults. Все варианты используют одни валидаторы;
scanner не ищет настройки в проверяемом репозитории или окружении.
[Полный формат и ограничения](reference/configuration.md).

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
| `ScanFile.status`, `reason` | analyzed/inherited/unverified/excluded/unsupported/error и машинная причина |
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
[Правила ID и сортировки](reference/reports.md).

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
исходных значений; пользовательские JSON/HTML содержат их полностью.

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
| Завершённый diff с проверенным baseline | 0/1 | baseline_verified |
| Ошибка файла или финальной проверки | 2, incomplete | none |
| Ошибка до полного плана/preflight | 2, error | none |

`complete` означает завершение заданной поддерживаемой текстовой обработки,
а не отсутствие секретов во всех объектах. Excluded/unsupported перечисляются
явно и не становятся обработанными. Неизменённые файлы diff имеют
`unverified/no_baseline` без baseline; даже A=B тогда не подтверждает весь B.
При проверенном baseline unchanged analyzed/inherited наследуют encoding/size
и `evidence_report_id` непосредственно предыдущего отчёта. Unsupported заново
классифицируются той же политикой. Приоритет 2 → 1 → 0, включая частичные находки.

Ошибки config/artifact/аргументов до запуска могут быть исключениями
`ConfigError`/`AnalysisError` с безопасным кодом. Операционные ошибки внутри
запуска превращаются в `ScanError`; отмена распространяется как
`asyncio.CancelledError` после очистки по умолчанию. Для CLI предусмотрен
`capture_cancelled=True`: после очистки возвращается неполный ScanResult со
завершёнными находками и ошибкой scan_cancelled. `summary()` — dev API, не
сериализованный scan_report и не доказательство baseline. `reports.build_report`
строит JSON v1, `report_validation.validate_report` проверяет runtime-инварианты.

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

В измерении этапа 4 на CPU ARM64 создание синтетического Git-репозитория и
snapshot 46 небольших файлов, включая ожидание readiness, заняли около
8.2 секунды. Это не SLA для 10 MiB, произвольных
репозиториев или concurrency>1. GPU/другие архитектуры не проверены.

## Воспроизводимая offline-проверка

Объединённый текущий прогон — в [CLI quickstart](cli-quickstart.md): он проверяет
установленный wheel и включает прежнюю direct-model parity на всём code-v1,
независимые координаты/value/context, длинный хвост, full-file diff и ошибки.
Scanner работает UID 65534/read-only без capabilities в loopback namespace
временного Analyzer с --network none; внешнего маршрута нет.

Для отдельной dev-проверки pipeline текущий рецепт содержит `httpx==0.28.1`
и `jsonschema[format]==4.26.0`. Собирайте новый локальный tag из минимального
контекста, не из корня checkout. Передайте context/runtime одного проверенного
комплекта из [admin build](admin/advanced-build.md), без подстановки старого lock:

```sh
ANALYZER_CONTEXT=/trusted/build/analyzer
RUNTIME_LOCK=/trusted/build/analyzer.runtime.lock.json
mkdir -p .build/scan-dev-new
cp docker/scan-test.Dockerfile .build/scan-dev-new/Dockerfile
docker build --platform linux/arm64 -t ru-llm-scanner-scan-tests:dev-new .build/scan-dev-new
python scripts/check_scan_integration.py \
  --context "$ANALYZER_CONTEXT" \
  --runtime-lock "$RUNTIME_LOCK" \
  --scanner-image ru-llm-scanner-scan-tests:dev-new \
  --output-dir .build/scan-verification-new
```

Установка dependencies требует подготовленного сетевого доступа на этапе сборки;
сам тест работает с `--pull never` и без внешнего маршрута. Harness копирует
только исходники `.py`, packaged `.json`, синтетический корпус и проверенные
assets; import/schema smoke выполняется до запуска модели. Старые dev images
не обновляются автоматически и должны использоваться с соответствующим кодом.
Сохранённые [результаты этапа 4](../verification/stage-4/README.md) остаются
историческим evidence, [этап 5](../verification/stage-5/README.md) фиксирует новый
код/образы и фактические ограничения QA. Формирование реальных отчётов не
устраняет известных ошибок модели на независимой разметке.
