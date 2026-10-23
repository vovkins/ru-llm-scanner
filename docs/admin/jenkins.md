# Jenkins: прямой доверенный CLI

Сначала подтвердите обычный build/test/scan под non-root учётной записью агента.
Доверенная установка scanner находится вне проверяемого/очищаемого workspace,
на том же rootful Docker daemon; config/baseline контролирует владелец CI.
[Предпосылки](README.md) и [build](build.md) одинаковы с обычным сервером.

Новый CLI сохраняет точные **0/1/2**. GNU Make для программного запуска не подходит:
он возвращает собственный код ошибки рецепта. Пример ниже фиксирует доверенные
пути и не подставляет build parameters в shell:

```groovy
node('scanner-native') {
    int status = sh(returnStatus: true, script: '''
        set +x
        /opt/ru-llm-scanner/scanner scan \
            --repo '/srv/git/example project' --commit HEAD
    ''')
    if (status == 1) {
        unstable('Scanner: найдены чувствительные данные; отчёт приватный')
    } else if (status != 0) {
        error('Scanner: ошибка или неполнота проверки')
    }
}
```

Пути/label заменяет администратор. Для diff используйте явно заданные refs и
одобренный baseline; например, команда из доверенного script:

```sh
/opt/ru-llm-scanner/scanner diff \
  --repo '/srv/git/example project' --from COMMIT_A --to COMMIT_B \
  --baseline '/srv/scanner baselines/approved-A.json' --require-baseline \
  --config '/srv/scanner config/approved.json'
```

Это пример с placeholders, не готовая SCM job. Не исполняйте pipeline/Makefile
из входного проекта и не добавляйте произвольные параметры разработчика в shell.
Для программного формирования аргументов используйте массив argv; разрешённые
refs/config/baseline определяет доверенная CI-логика. Baseline нельзя брать из
непроверенного workspace или продвигать после кода 1/2.

## Файлы и ресурсы агента

SCM-процесс заранее получает все нужные объекты и прекращает изменение клона
на время scan. Docker host и агент видят одни и те же абсолютные bind-пути.
Controller может быть отдельно; установка daemon/context/credentials не выполняется
scanner. Dedicated Docker agent не предоставляется произвольным PR pipelines.

По умолчанию отчёт создаётся в HOME/XDG каталоге учётной записи агента, вне клона;
его абсолютный путь печатается после запуска. Для машинного получения артефактов
задайте `--output` с уникальным новым приватным каталогом и существующим parent
**вне** очищаемого workspace. Если такой путь уже занят, запуск отклоняется.
Не архивируйте «последний найденный» старый report после раннего отказа.

JSON/HTML содержат полные значения. В этом примере автоматической публикации
artifacts/HTML нет. Если она нужна, владелец CI отдельно ограничивает job/workspace/
artifact/backups ACL и retention, сохраняет process status и точный output текущего
запуска. Локальные `0700`/`0600` сами по себе не задают RBAC Jenkins.

Подбирайте limits/concurrency по целевому агенту. Внешний Jenkins timeout должен
оставлять время на run timeout, stop grace и cleanup. Потеря агента/SIGKILL может
требовать [операторского восстановления](operations.md#потерянный-запуск).
Продвижение baseline — отдельный доверенный процесс после завершённого exit 0.

## Готовый доверенный adapter

Для job с restricted artifacts подготовлен
[Jenkinsfile.workflow](../../examples/jenkins/Jenkinsfile.workflow) и
[run_workflow_scan.py](../../examples/jenkins/run_workflow_scan.py). Администратор
задаёт `SCANNER_HOME`, корни repositories/configs/baselines и agent label в
доверенной pipeline-конфигурации; пользователь выбирает только разрешённые имена
и refs. `SCANNER_HOME` указывает на заранее собранную и проверенную установку,
расположенную вне очищаемого workspace. Ручной deployment JSON ему не нужен.

Adapter формирует argv, запускает `scanner scan|diff`, получает process0/1/2 и
пишет безопасный `scan-status.json`. Человеческие stdout/stderr не разбираются и
не копируются в Jenkins console. Для0/1 обязательны оба private report-файла.
Ранний отказ/сигнал даёт2; успешный status не наследуется от предыдущего запуска.

В этом варианте только временные reports/status находятся в отдельном workspace
job (`scan-results`,0700/0600), который очищается перед build; установка, input,
config и baseline остаются вне workspace. Одновременные builds одной job
запрещены, разные jobs получают разные workspace/output. Archives содержат полные
значения: до включения примера настройте доверенные job/artifact ACL и retention.
`archiveArtifacts` копирует текущие файлы, но не продвигает baseline автоматически.

Одна пара контейнеров по умолчанию ограничена3GiB/2CPU Analyzer и1GiB/1CPU
scanner. Для двух параллельных пар учитывайте8GiB контейнерных лимитов плюс host,
Jenkins JVM, Docker и запас;4CPU суммарно распределяются планировщиком. Ограничения
контейнеров не являются требованиями SLA. Большие файлы могут требовать явных
бюджетов из [эксплуатационного руководства](operations.md).

Отмена/timeout пересылают TERM trusted CLI и дают ему время на cleanup. После
жёсткой потери агента оператор сначала идентифицирует точную установку и
workspace, затем завершает только её процессы и Compose project; глобальный
`docker prune`/остановка соседних jobs не применяется. Сам pipeline не меняет
production credentials/RBAC/daemon и не настраивает Docker host.

## Что проверено

Настоящий отдельный Jenkins AMD64 pilot прошёл declarative validation и13
завершённых сценариев:0/1/2, strict baseline, invalid ref/config/baseline,
foreign profile, unbuilt trusted installation без старого report, две параллельные
jobs, timeout/cancel и hard agent loss с ограниченным operator cleanup.
Private artifacts содержат полные synthetic values, console — безопасную сводку;
baseline не продвигается автоматически. Docker project IDs наблюдались отдельно
по argv/WORKSPACE, acquisition запрещён, собственные ресурсы проверены после jobs.
[Точные source/controller/plugins/resources и результаты](../../verification/simple-workflow-stage-6/README.md).

Это native Ubuntu24.04 AMD64/reference pilot, не проверка production Jenkins,
корпоративных ACL/PKI, rootless Docker, GPU или отдельного ARM64 Jenkins. Native
ARM64 CLI/build/test/scan проверены отдельно. Исторический v0.2.0 pilot относится
к [прежнему explicit adapter](jenkins-explicit.md); он сохраняется совместимым.
