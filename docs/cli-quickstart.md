# Запуск CLI и работа с отчётами

Доступны `snapshot`, `diff`, JSON/HTML v1 и baseline chain. Штатные Docker/Compose,
перенос образов и пример Jenkins относятся к этапу 6. Ниже — проверенный dev
интерфейс; при анализе зависимости/веса не скачиваются.

## Установка и доверенные assets

Нужны Python 3.11+, Git и доступный закреплённый Analyzer, подготовленный по
[руководству](analyzer.md). Установка/сборка могут обращаться к источникам
зависимостей; отделяйте их от закрытого запуска.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e . -r requirements-dev.txt
.venv/bin/ru-llm-scanner --help
.venv/bin/ru-llm-scanner --version
.venv/bin/python scripts/prepare_scan_engine.py \
  --context .build/analyzer \
  --runtime-lock locks/analyzer-cpu-linux-arm64.runtime.lock.json \
  --output .build/scanner-engine
```

Export требует новую папку и проверяет исходный подготовленный контекст и
runtime lock. Получаются ровно `source-lock.json`, `runtime-lock.json`,
`dictionary_policy.py`, `dictionary.json`; исходный проект и веса не копируются.
Передавайте папку через `--engine-dir`. Без аргумента используется фиксированный
`/opt/ru-llm-scanner/engine`, а не поиск в cwd/сканируемом проекте/окружении.
Это доверенный вход оператора; scanner проверяет хеши и API-подпись, но не
доказывает подлинность подменённого lock цифровой подписью.

## Первый снимок

Analyzer должен уже работать по адресу, доступному из окружения CLI. Пример
`http://analyzer:5001` — внутреннее имя сервиса, не публичный API. Эксплуатационная
сеть и запуск контейнеров будут оформлены на этапе 6; полностью воспроизводимая
проверка с собственными временными контейнерами приведена ниже.

```bash
.venv/bin/ru-llm-scanner snapshot \
  --repo /repo --commit HEAD --output /reports/initial \
  --engine-dir .build/scanner-engine --analyzer-url http://analyzer:5001
```

Команда читает состояние коммита из Git-объектов, без checkout и исполнения
проекта. Рабочие/staged/untracked файлы не анализируются. Object store должен
оставаться неизменным во время запуска. [Допустимые клоны и кодировки](git-reader.md).

В новой/пустой output-папке появляются `report.json` и самостоятельный
`report.html`. Найденные значения и контекст полные; консоль содержит JSON-сводку
без них: SHA A/B, итог, охват, счётчики и безопасные коды ошибок.

| Код | Действие оператора |
| --- | --- |
| `0` | Заданная обработка завершена без находок; учитывайте assurance и исключения |
| `1` | Обработка завершена, просмотрите все находки |
| `2` | Ошибка/неполнота/ошибка записи; просмотрите ошибки и не используйте результат как baseline |

Проверяйте код процесса, а не наличие файла. Находки сохраняются при ошибках
других файлов и при SIGINT после завершения части обработки. Отмена дожидается
локальных workers; она не гарантирует остановку вычислений сервером Analyzer.

## Переходы и baseline

Baseline хранится в доверенном процессе и допускается только после кода `0`,
проверки профиля/дерева/полноты и с подходящими правами. Отчёт с находками,
`changed_files_only`, ошибками или `contract_example` не подходит.

```bash
.venv/bin/ru-llm-scanner diff \
  --repo /repo --from COMMIT_A --to COMMIT_B --output /reports/check-B \
  --baseline /reports/initial/report.json --require-baseline \
  --engine-dir .build/scanner-engine --analyzer-url http://analyzer:5001

# Только если check-B завершён с 0 и сохранён доверенным процессом:
.venv/bin/ru-llm-scanner diff \
  --repo /repo --from COMMIT_B --to COMMIT_C --output /reports/check-C \
  --baseline /reports/check-B/report.json --require-baseline \
  --engine-dir .build/scanner-engine --analyzer-url http://analyzer:5001
```

Изменённые файлы и новые пути переименований анализируются целиком. Неизменённые
analyzed/inherited получают `inherited` с encoding/size и ID непосредственно
предыдущего отчёта. Excluded сохраняются по текущему scope; unchanged unsupported
переклассифицируются той же политикой, их содержимое не становится проверенным.

Любой предъявленный неподходящий baseline даёт `2`, даже без strict-флага.
Для намеренной проверки только изменений запустите diff без baseline:
результат будет `changed_files_only`, unchanged — `unverified/no_baseline`,
включая A=B. Новая модель/правила/область требуют snapshot.
[Подробная матрица](baseline.md), [профиль и параметры](configuration.md).

## Файлы и ошибки

Output должен быть вне репозитория. Непустая папка, symlink в пути (включая
родителей), конкурирующий writer и недоступная запись отклоняются. На macOS
используйте `/private/tmp`, если нужен временный путь: `/tmp` — системный symlink.
Новые каталоги имеют права `0700`, файлы `0600`. Заранее созданная пустая папка
сохраняет свои права; ответственность за доступ к каталогу остаётся у оператора.

Публикация каждого файла атомарна: временный файл + fsync, создание без замены
через hard link; исправление собственного файла — atomic replace. Старые
результаты не перезаписываются. Общей транзакции двух файлов нет. При сбое
построения/записи scanner пытается сохранить JSON с `report_write_error` и
обновить HTML; при полном отказе файловой системы это может быть невозможно.
Ранее записанный файл может отражать состояние до сбоя — окончательный код
команды всё равно `2`, такой запуск нельзя повышать до доверенного baseline.

Строгий baseline ограничен 128 MiB, принимается обычный файл без symlink;
превышение/битый JSON/duplicate keys/NaN дают `baseline_invalid`. При отказе
preflight до проверки предъявленного baseline он имеет `invalid` с причиной
`verification_not_completed`, а не считается подтверждённым.

Откройте HTML локально: фильтры по файлу, категории, источнику и поиск работают
без сервера/CDN. Группировка меняет представление, не теряя мест. Сырые пути
показаны в base64 вместе с ID для различения одинаковых display paths.
Управляющие/невидимые символы отображаются как `\uXXXX`; оригинал сохранён
в JSON. Значения/пути не превращаются в активные URL или исполняемый HTML.

## Воспроизводимая проверка реальной моделью

После подготовки/seal Analyzer соберите wheel и dev-образ из минимального
контекста. Сборка может использовать интернет/зеркало; следующий launcher
запускает анализ без внешней сети.

```bash
.venv/bin/python -m pip wheel --no-deps --wheel-dir .build/stage-5/wheels .
mkdir -p .build/stage-5/image-context
cp docker/cli-test.Dockerfile .build/stage-5/image-context/Dockerfile
cp .build/stage-5/wheels/*.whl .build/stage-5/image-context/
docker build --platform linux/arm64 -t ru-llm-scanner-cli-tests:stage5 \
  .build/stage-5/image-context
.venv/bin/python scripts/check_cli_integration.py \
  --runtime-lock locks/analyzer-cpu-linux-arm64.runtime.lock.json \
  --context .build/analyzer --scanner-image ru-llm-scanner-cli-tests:stage5 \
  --output-dir .build/stage-5/real-model
```

Контекст содержит только Dockerfile и wheel, не корень проекта. Launcher
проверяет platform Image ID Analyzer, монтирует только перечисленные assets/
fixtures/исходники read-only, запускает scanner UID 65534 без capabilities
в loopback namespace временного Analyzer с `--network none`. Установленный
wheel сверяется с исходниками, вызывается настоящий console entry point.
Проверяются code-v1, baseline A→B→C, ошибки и отсутствие значений в консоли;
собственные контейнеры удаляются после завершения. Внешние проекты не нужны.

Синтетические HTML/JSON для визуальной QA остаются в `.build/.../qa` и только
там экспортируются с `0644`, чтобы быть доступны на хосте. Пользовательские
отчёты сохраняют `0600`. В публичное evidence входят только хеши/счётчики/версии,
без найденных значений. [Результаты этапа 5](../verification/stage-5/README.md).

Известные ошибки качества code-v1 не скрываются: функциональная проверка
сериализации и baseline не делает модель безошибочной. [Качество и границы](../verification/stage-4/README.md).
