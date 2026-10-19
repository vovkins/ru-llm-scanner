# Замечания ревью

Все ссылки на код относятся к `336feb64b201b0e9b807059f3d60b50fdee41ebb`.
P0 — критический блокер, P1 — высокий приоритет до итоговой приёмки,
P2 — значимая проблема/усиление с указанными условиями, P3 — удобство сопровождения.
Классификация и открытые статусы собраны в [обзоре](README.md).

RV-01–RV-05 исправлены/выполнены в отдельно согласованном этапе 2.
[Новые результаты](../../verification/operations-stage-2/README.md) отделены от
исторических воспроизведений ниже; ссылки на `336feb6` остаются доказательством
исходного поведения. DOC-01/DOC-02 и TEST-01 остаются открытыми для этапов 3–4.

## RV-01 — P1: невалидный ответ launcher даёт Jenkins успешный exit

Место: [run_scan.main, строки 92–100](https://github.com/vovkins/ru-llm-scanner/blob/336feb64b201b0e9b807059f3d60b50fdee41ebb/examples/jenkins/run_scan.py#L92).
Перед json.loads code уже заменён на успешный process.returncode. При ошибке
разбора или обращении .get к списку except только выполняет pass. Код остаётся 0.

Условия: дочерний launcher завершился 0, но stdout пуст, невалиден либо имеет
неправильный тип. Это воспроизведение нарушения границы между двумя локальными
процессами; штатный launcher обычно выдаёт корректную сводку. Захват launcher
злоумышленником или наличие настоящего Jenkins для воспроизведения не требуются.

Факт: пустой/повреждённый JSON и список дали process exit 0 и console exit 0 при reports_available=false.
Для пустого/повреждённого JSON сохранён status.exit_code=2; для списка сохранён
сам список. Дополнительный случай exit_code=false тоже принят как 0 из-за
равенства bool/int в Python. Jenkinsfile обрабатывает return code и может оставить build успешным.
Ожидание: любой отказ разбора/типа/согласованности результата даёт exit 2 и
единый валидный error-status, без вывода сырого stdout/stderr.

Доказательство: jenkins_invalid_summary в [observations.json](observations.json),
[reproduce.py](reproduce.py). Положительный контроль корректного error-summary
вернул 2. Два существующих Jenkins unit тестируют command/path guard rails,
но не main и некорректный stdout; production extras покрывает штатные 0/1/2.

Предлагаемое исправление: присваивать итоговый code только после полной
проверки summary; в любом except возвращать code 2 и нормализованный status.
Проверить int без bool, допустимые exit codes, согласованность процесса/summary,
безопасный набор полей, stderr, сигнал и запись status. Отдельно проверить
отсутствующие артефакты при заявленных завершённых 0/1; при ранней ошибке 2
их отсутствие допустимо. Критерий: все негативные случаи дают 2, штатные 0/1/2
сохраняются, status и console согласованы, private values не печатаются.

## RV-02 — P2: FIFO вместо deployment lock блокирует preflight

Место: [docker_scanner.strict_json, строки 63–72](https://github.com/vovkins/ru-llm-scanner/blob/336feb64b201b0e9b807059f3d60b50fdee41ebb/scripts/docker_scanner.py#L63).
stat().st_size не проверяет тип файла; FIFO имеет размер 0 и проходит лимит.
Затем read_text блокируется при open до разбора JSON и до Docker.

Условия: оператор указал специальный файл вместо доверенного lock. В воспроизведении
создан собственный FIFO, `verify --deployment-lock FIFO` не завершился за 2 секунды
и subprocess.run его убил. Встроенного ограниченного отказа на этом пути нет;
scan run-timeout применяется позже и не решает проблему preflight.
Реальных пакетов/locks и объектов чужого репозитория проверка не касалась.

Доказательство: fifo_deployment_lock в [observations.json](observations.json).
Ожидание: ограниченный по времени отказ с кодом 2/invalid_lock без Docker.
Лимит 4 MiB также должен относиться к фактически прочитанным данным, а не только
к ранее полученному stat. Текущая модель доверия не защищает от активного
злоумышленника-хоста; это не следует объявлять обходом изоляции scanner.

Предлагаемое исправление: проверять regular file по открытому descriptor,
использовать открытие, не блокирующееся на FIFO, и bounded read. Политику
симлинков определить явно. Сохранить stdlib-only host launcher и strict JSON.
Критерий: FIFO/директория/oversize/повреждённый JSON дают bounded 2, валидный
lock проходит, дочерних процессов/потоков после проверки не остаётся.

## RV-03 — P2: dev scan image отстал от runtime dependencies

Место: [docker/scan-test.Dockerfile:6](https://github.com/vovkins/ru-llm-scanner/blob/336feb64b201b0e9b807059f3d60b50fdee41ebb/docker/scan-test.Dockerfile#L6).
Установлен только httpx. Текущий pipeline импортирует baseline → report_validation
→ jsonschema, поэтому рецепт этапа 4 больше не может запускать текущую версию.
Штатный production image и CLI test image уже содержат нужную зависимость.

Факт: в существующем `ru-llm-scanner-scan-tests:stage4` без сети, с read-only mount
только src, `import ru_llm_scanner.pipeline` дал missing_module=jsonschema.
Dockerfile подтверждает отсутствие установки. Новый image не собирался;
это наблюдение локального старого image плюс дефект актуального рецепта.

Предлагаемое исправление: синхронизировать pinned dev dependencies и проверить
минимальный импорт и packaged schema в network-none окружении. Curated copy
check_scan_integration сейчас содержит только .py; включить необходимые JSON
resources, чтобы проверка report API не зависела от другого installed package.
Затем выполнить настоящий scan harness из заново собранного dev image.
Критерий: документированный рецепт запускается на текущем исходном дереве;
реальный offline-прогон подтверждает pipeline, production locks не меняются.

## RV-04 — P2: legacy parity harness имеет избыточный доступ к checkout

Место: [check_analyzer_integration.py:38–61](https://github.com/vovkins/ru-llm-scanner/blob/336feb64b201b0e9b807059f3d60b50fdee41ebb/scripts/check_analyzer_integration.py#L38).
Read-only mount всего root даёт test container доступ к .git, .build, локальным
отчётам и любым другим файлам checkout, хотя нужны лишь allowlisted code/assets.
Постоянное имя мешает параллельным запускам; нет --pull never, --cap-drop ALL,
no-new-privileges и явной проверки фактического platform Image ID перед run.
`--network none` ограничивает контейнер, не получение образа Docker daemon.

Подтверждена конфигурация argv чтением кода; не выполнялись чтение приватных
файлов, попытка скачивания или эксплуатация. Pinned Analyzer доверенный,
производственный launcher этот путь не использует. Это замечание по минимизации
доступа dev tooling, не доказанная утечка.

Предлагаемое исправление: переиспользовать curated подход более нового
check_rehearsal_parity без изменения тестируемого механизма; уникальное имя,
точная идентичность, pull never, non-root и ограниченные mounts/cleanup.
Критерий: argv/dry-run не содержит mount корня checkout; отрицательная проверка
отсутствующего образа завершается локально, реальные raw/patched проверки проходят.

## RV-05 — P2: разная политика существующего output у двух entry points

Место: [ReportDirectory:35–45](https://github.com/vovkins/ru-llm-scanner/blob/336feb64b201b0e9b807059f3d60b50fdee41ebb/src/ru_llm_scanner/output.py#L35)
и [prepare_output:155](https://github.com/vovkins/ru-llm-scanner/blob/336feb64b201b0e9b807059f3d60b50fdee41ebb/scripts/docker_scanner.py#L155).
Python writer принимает пустую 0777 папку и сохраняет её mode; launcher её
отвергает. В обоих созданные файлы 0600. Поведение Python CLI явно разрешено
[действующим quickstart](../cli-quickstart.md), ответственность оставлена оператору.

Доказательство: public_output в [observations.json](observations.json).
Это не нарушение документированного CLI-контракта и не подтверждение утечки.
Однако общая инструкция «приватный output» зависит от выбранного entry point,
а чужой writable каталог допускает вмешательство в имена/доставку артефактов.

Предложение для явного согласования этапа 2: единообразно отвергать существующую
неприватную/чужую конечную папку через fstat descriptor, сохраняя её права.
Не выполнять автоматический chmod/chown. Новые папки остаются 0700, файлы 0600.
Это видимое ужесточение preflight Python CLI; профиль распознавания не меняется.
Критерий: свои 0700/новые output работают, небезопасные отклоняются без изменения
существующих данных; symlink/race/atomicity защиты сохраняются.

## Документация и воспроизводимость

DOC-01: [Analyzer build/seal](../analyzer.md) создаёт `.build/runtime-cpu.lock.json`,
а [offline-build](../offline-build.md) начинает export engine с `locks/analyzer-...`.
Это measured lock прежнего стенда; новая сборка может получить другой Image ID.
Нужны два последовательных маршрута: import готового доверенного пакета и fresh
build с передачей именно его lock во все дальнейшие команды. Статически
подтверждена необходимость ручного выбора; новый clean-host walkthrough не выполнялся.
Исправление относится к этапу 3, проверка — к этапу 4; ослаблять Image ID validation нельзя.

DOC-02: в README/docs map смешаны хронология этапов, API и эксплуатационные ссылки.
Нет отдельных завершённых руководств двух ролей, GitHub description пуст.
Нужны короткий README, role guides, общий reference, явные артефакты передачи
между администратором и пользователем и безопасный пример отчёта. Это этап 3.

TEST-01: `tests/cli_fixtures.py:16` и `CLITests.setUpClass` требуют .build/analyzer;
без него CLI tests skipped. Это документированное предусловие, не новый дефект.
Нужны явные asset-free/asset-required/real-model группы и воспроизводимая
подготовка; полный результат допускается только без skipped. Архитектурное
отделение stub CLI fixtures можно вынести отдельным решением после измерения
стоимости; обязательные upstream/dictionary проверки удалять нельзя.
