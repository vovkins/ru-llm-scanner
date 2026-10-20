# Интеграция с Jenkins

[Jenkinsfile](../../examples/jenkins/Jenkinsfile) и
[Python adapter](../../examples/jenkins/run_scan.py) — пример доверенного pipeline.
Действующий Jenkins, credentials/jobs/RBAC пользователя не изменяются. На данном
стенде выполнена локальная последовательность adapter → production launcher →
реальные контейнеры с кодами 0/1/2 и baseline; Jenkins controller/Groovy plugins
здесь отсутствовали. Нативная AMD64 проверка настоящего Jenkins разрабатывается
в [#33](https://github.com/vovkins/ru-llm-scanner/issues/33);
[текущий статус](../../verification/linux-amd64/README.md). До её завершения
прохождение Declarative validation и полноценного pipeline не заявляется.

## Подготовка агентом CI

Владелец предоставляет dedicated non-root CPU ARM64 agent с Python 3.11+,
Docker/Compose и готовыми образами из [доверенного offline-пакета](build.md).
Установите scanner/scripts/пример в `/opt/ru-llm-scanner`, доступный агенту для
чтения. Pipeline/script берутся из доверенной версии scanner, **никогда из
проверяемого checkout**. Label/пути/retention в примере заменяются администратором.
Docker-доступ привилегирован; не выдавайте этот агент произвольным PR pipelines.

В текущем adapter администратор задаёт **абсолютный путь к одобренному deployment**
через `SCANNER_DEPLOYMENT_LOCK`, например `/srv/ru-llm-scanner/deployment.json`.
Переменная относится к доверенной конфигурации агента/pipeline, не к параметрам
разработчика; URL, относительный путь, symlink и отсутствующий файл отвергаются.
Выбранный комплект должен соответствовать архитектуре Docker daemon.

[AMD64 Jenkinsfile](../../examples/jenkins/Jenkinsfile.amd64) уже содержит эту
переменную и label `scanner-cpu-amd64`; его приёмка ещё выполняется.
Для совместимости без переменной остаётся исторический default
`$SCANNER_HOME/locks/scanner-cpu-linux-arm64.deployment.json`. Это поведение
старого ARM64 примера, а не автоматический выбор актуального image после сборки.
Для новой установки передавайте deployment её пакета явно; штатные locks в Git
ради этого не изменяются. Старый launcher/adapter из v0.1.0 новую переменную
не поддерживает: переносите согласованный комплект скриптов целиком.

До настройки job проверьте этот точный комплект non-root учётной записью агента:

```sh
python3 /opt/ru-llm-scanner/scripts/docker_scanner.py verify \
  --deployment-lock /srv/ru-llm-scanner/deployment.json
```

Установка включает `scripts/docker_scanner.py`, выбранный lock,
`examples/jenkins/run_scan.py` и trusted Jenkinsfile. Документация/происхождение
передаются вместе с ними. Значения `SCANNER_HOME` и roots в примере меняет
владелец CI; scanner сам не редактирует jobs/credentials/RBAC.

До scan другой доверенный SCM-процесс готовит self-contained Git-клон под
`/srv/ru-llm-scanner/repositories/REPOSITORY_NAME`. A/B и все reachable objects
должны быть доступны: shallow clone допустим только при наличии нужных объектов.
Scanner не выполняет fetch/unshallow/checkout. Не используйте shared alternates,
linked worktrees, `.git` с внешней metadata и clone, изменяемый параллельно.
Рабочие/staged/untracked файлы не входят в состояние выбранного коммита.

Пример `skipDefaultCheckout(true)` не подготавливает SCM автоматически. Вход,
trusted configs и baseline располагаются **вне workspace этого job**: `deleteDir()`
очищает workspace перед новым запуском, чтобы не архивировать прежний clean
report при ранней ошибке. Подготовка SCM при необходимости идёт отдельным
доверенным этапом до вызова примера, с собственными credentials вне scanner.

## Параметры и результат

| Параметр | Значение |
| --- | --- |
| `SCAN_MODE` | `snapshot` или `diff` |
| `REPOSITORY_NAME` | Имя подготовленного клона внутри доверенного root |
| `REF_A`, `REF_B` | Явные refs/commit A и B; A нужен только для diff |
| `CONFIG_NAME` | Имя одобренного файла в `/srv/ru-llm-scanner/configs`, либо пусто |
| `BASELINE_NAME` | Имя доверенного JSON в `/srv/ru-llm-scanner/baselines`, либо пусто |
| `REQUIRE_BASELINE` | Для diff по умолчанию true |

Имена — один basename без traversal/URL/symlink. Refs передаются как отдельные
argv без shell/Groovy interpolation. Не задавайте в параметрах найденные значения.
Конфигурационный/базовый каталоги защищаются владельцем CI от записи разработчиками
и недоверенными jobs. Само имя `approved.json` не доказывает происхождение.

0 оставляет build успешным; 1 помечает его UNSTABLE с находками; 2/иной код
останавливает stage как FAILURE. `post always` архивирует доступные report.json,
report.html и безопасный scan-status.json с `allowEmptyArchive`. При раннем
отказе отчётов может не быть; status/exit остаётся отказом. Сигналы adapter
пересылает launcher для cleanup. SIGKILL/потеря агента требуют
[операторского восстановления](operations.md). Jenkins timeout должен быть
больше `run-timeout` + startup/stop/cleanup grace; пример выделяет 75 минут.

Adapter принимает только JSON-объект с `exit_code` (целое 0/1/2, не bool),
`error` (null или ограниченный код) и необязательным `project` доверенного launcher.
Code должен совпасть с кодом дочернего процесса. Пустой/битый ответ, duplicate keys,
лишние поля, stderr, сигнал или исключение означают `2`; сырые ответы не
попадают в status/console. Для `0`/`1` обязательны оба непустых обычных файла
`report.json`/`report.html`, принадлежащие UID агента и без group/other permissions,
в таком же приватном каталоге. Это проверка артефактов доверенного launcher,
а не независимое доказательство полноты анализа.

Workspace должен существовать; `scan-status.json` должен отсутствовать,
`scan-results` — отсутствовать либо быть пустым приватным каталогом агента.
Adapter не перезаписывает старый status/отчёты. При невозможности записи status
итоговый код процесса остаётся `2`; старый файл не является статусом нового
запуска. Отсутствующий/недоступный WORKSPACE также даёт безопасную сводку и `2`.

## Baseline и чувствительные артефакты

Продвижение baseline не автоматизировано этим примером. Только доверенный процесс
CI/оператор переносит JSON **из завершённого запуска с exit 0**, с сохранённой
идентичностью job/сборки/профиля и подходящими ACL. Никогда не продвигайте код 1/2,
наличие файла без статуса запуска или артефакт по пользовательскому URL. Runtime
дополнительно сверяет schema/semantic invariants, A/tree/profile; это не подпись
происхождения. Новая модель/правила/область требуют нового полного snapshot.

Полные находки и контекст остаются в JSON/HTML. Перед включением архивации
владелец ограничивает доступ к job/workspace/artifacts/backups, задаёт срок хранения,
аудит доступа и защищённую доставку. `buildDiscarder` в примере задаёт только
пример retention, **не RBAC и не гарантию удаления всех копий/backup**. HTML
просматривайте через разрешённую приватную выдачу; не добавляйте автоматический
публичный HTML publisher. Не печатайте JSON/HTML и параметры с данными в console.
