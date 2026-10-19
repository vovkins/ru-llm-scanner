# Этап 6: production Docker, перенос и пример Jenkins

Проверено 2026-10-19: macOS Apple Silicon, Docker Desktop 29.6.1 / Compose 5.2.0,
CPU Linux ARM64, VM 8 GiB / 10 CPU. Этап согласован в
[#11](https://github.com/vovkins/ru-llm-scanner/issues/11). Runtime release/registry
не публиковались; действующий Jenkins не изменялся.

| Свидетельство | Результат |
| --- | --- |
| [Unit](unit-tests.json) | 131 tests, 0 failures/errors/skipped |
| [Production Compose](docker-verification.json) | 25 сценариев, RO host clone, A→B→C, 0/1/2, faults/signals/parallel |
| [Дополнительные проверки](extras-verification.json) | 11 сценариев: permissions, local Jenkins, checksum/ID/context negatives |
| [OOM и частичная отмена](fault-verification.json) | Kernel OOMKilled подтверждён; завершённая находка сохранена при SIGTERM |
| [Реальный CLI](cli-verification.json) | 9 сценариев установленного wheel, source/schema match |
| [Независимый code-v1](scan-verification.json) | 46/46 parity; TP 33 / FP 13 / FN 4 |
| [Deployment/inventory](../../locks/scanner-cpu-linux-arm64.deployment.json) | Exact image IDs, SHA-256 wheel/deb/assets/Dockerfile |
| [Финальная сверка](completion-checks.json) | Cleanup, неизменный proxy, повторный offline build/transfer и contracts/format |

Scanner platform/reference ID:
`sha256:257f7d6918bc360a28fb52e09022a40940691c691a9556f6aa5b9ea32485c73d`.
Wheel SHA-256:
`3308f07f9d6352b373f911738e05273e418198b3728b084ed9318726acb37583`.
Analyzer platform ID прежний:
`sha256:dac76ca6f7f37d61f7a3ad4db1d56d68dcad14d9e44354252dcfbf3c208c5104`.
Его root reference ID и все assets сохранены в deployment/runtime locks.
Словарь, модель, source/runtime lock Analyzer, thresholds и корпус не изменены.

Штатные сервисы: non-root UID/GID 501:20, root FS read-only, drop ALL capabilities,
no-new-privileges, tmpfs, repo bind ro, output rw, отдельные config/baseline ro.
Проверены фактический отказ записи через repo mount, internal network ровно двух
сервисов, отсутствие published ports/default route/socket/credential mounts и
отключённые container logs. Лимиты: scanner 1 CPU/1 GiB, Analyzer 2 CPU/3 GiB.
Это рабочие budgets на данном корпусе, не максимальная ёмкость для любого repo.
В отдельном fault-прогоне два моментных memory samples Analyzer составили
1.168 и 1.623 GiB из 3 GiB; это не измерение пика. После снижения собственного
лимита до 128 MiB подтверждён `OOMKilled: true`, launcher вернул 2. При SIGTERM
во время следующего большого файла одна завершённая находка сохранена в отчёте
с кодом 2; вход не изменился, собственные ресурсы удалены.

Полные synthetic JSON/HTML и assertion logs находятся только в игнорируемой
`.build/stage-6/`. Публичные evidence содержат технические hashes/счётчики/категории,
без найденных значений. Хеши относятся к конкретному прогону; production, extras,
CLI и unit запускались на разных шагах работы, поэтому их source inventories
не обязаны совпадать после добавления последующих transfer/diagnostic проверок.

## Что проверено

Snapshot A → diff A/B → diff B/C с обязательным baseline, полные приватные
0600 отчёты, доступные оператору, clean/findings/incomplete. Рабочие, staged,
untracked файлы и metadata входа сохранились. Спецсимволы/пробелы/`$` в пути и
refs не выполняются; `.env` клона не выбирает Compose-конфигурацию.

Ошибки config/baseline/profile/ref/missing object/лимита, ready/analyze/run timeout,
SIGINT/TERM, crash scanner/Analyzer, ограничение RAM Analyzer, missing image,
existing/public/unwritable output и inaccessible input дают 2. Ранние ошибки
могут не оставить отчёта; отсутствие артефакта не считается clean. После обычных
проверок собственных контейнеров/сетей не осталось. Два параллельных запуска
завершились независимо; 7 чужих работающих контейнеров сохранили Running/StartedAt.

Export/save → SHA-256 → load → platform-ID verify выполнен в том же Docker store,
без удаления исходных образов и без registry. Полный пакет включает images.tar,
deployment.json и engine locks/assets; checksum/ID/context corruption отвергнуты.
Это не испытание второго физического offline-хоста.

Jenkins Python adapter локально выполнил clean, diff с доверенным baseline,
findings, missing-ref и отказ пользовательскому URL baseline. Console содержит
безопасный статус, scanner reports полные и приватные. Jenkins controller,
Declarative linter/plugins, RBAC/retention владельца не тестировались и не менялись.

Установленный production wheel повторно прошёл предыдущий offline CLI harness
и code-v1. Качество неизменно: 37 ожидаемых мест, exact precision 71.74%, recall
89.19%. Полностью пропущен телефон; bearer/base64/INN имеют ошибки категорий/
границ, присутствуют лишние срабатывания. Ни упаковка, ни baseline не исправляют
эти ограничения. Прежняя визуальная QA HTML остаётся [в этапе 5](../stage-5/README.md).

## Воспроизведение и границы

Команды: [сборка/перенос](../../docs/offline-build.md),
[production запуск](../../docs/docker-quickstart.md),
[harness](../../docs/development.md), [Jenkins](../../docs/jenkins.md).
Подготовка корпоративных CA/proxy поддержана явными secret mounts; реальная
корпоративная инфраструктура не воспроизводилась. GPU/AMD64/Windows-native/
Linux-host UID mapping и другой Docker image store требуют собственных испытаний.

Нет защиты от администратора daemon/активного изменения object store на хосте;
SIGKILL/daemon loss может потребовать ручного cleanup точного проекта. Queue
не ограничивает память всех результатов/модели. CPU join может продлить deadline,
а JSON/HTML не являются общей транзакцией. Инфраструктурный exit 2 важнее прежнего
clean artifact. Лицензия/release/внешние настройки не изменялись. Полная сквозная
приёмка и репетиция обновления/отката Analyzer относятся к отдельно согласуемому
этапу 7.
