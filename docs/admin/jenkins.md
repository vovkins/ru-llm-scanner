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

## Что проверено

Команды нового CLI проверяются native AMD64/ARM64 walkthrough; этот Groovy пример
не означает новый настоящий Jenkins pilot. Он запланирован в этапе6 #38 и не
меняет production jobs/credentials/RBAC. Историческая настоящая приёмка Jenkins
v0.2.0 (13 сценариев) относится к [explicit adapter](jenkins-explicit.md) и своим
images/locks. Его [Jenkinsfile](../../examples/jenkins/Jenkinsfile),
[AMD64-вариант](../../examples/jenkins/Jenkinsfile.amd64) и
[adapter](../../examples/jenkins/run_scan.py) сохранены совместимыми; они требуют
explicit deployment и не являются новым Make/CLI интерфейсом.
