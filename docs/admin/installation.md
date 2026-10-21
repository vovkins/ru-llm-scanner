# Установка из готового offline-пакета

Предусловия и проверенная среда — в [руководстве администратора](README.md).
Если пакета ещё нет, сначала выполните [fresh build и export](build.md).
Здесь ничего не скачивается из registry и не собирается.
Для AMD64 выберите пакет `cpu-linux-amd64`, для ARM64 — `cpu-linux-arm64`.
Архитектура Docker **server** должна совпасть с `platform` deployment; чужая
платформа вызывает `daemon_platform_mismatch`, автоматическая эмуляция не включается.
После смены профиля нужен новый полный snapshot для baseline. Опубликованный
v0.1.0 содержит ARM64. Поддержка AMD64 включена в `main` через PR #35, новые образы
и релиз не опубликованы; порядок сборки и установки — в [серверной инструкции](linux-amd64.md).
Маршрут import→verify→snapshot и последующие пользовательские команды пройдены
на source checkpoint `2588571` в новой минимальной установке без dev venv/src/proxy/context:
[ready walkthrough](../../verification/operations-dependencies/ready-walkthrough.json).
[Итоговый контроль](../../verification/operations-stage-5/README.md) проверил
этот комплект на кандидате `e5e3115`; после слияния выполнен
[новый control на main](../../verification/operations-main-integration/README.md).
Другой физический offline host не испытывался.

## Получить и разместить комплект

Ответственный за сборку передаёт по доверенному каналу:

- согласованную версию `scripts/docker_scanner.py` и соответствующую документацию;
- полный каталог export: `images.tar`, `deployment.json`, `checksums.json`,
  `engine/source-lock.json`, `engine/runtime-lock.json`, `engine/dictionary_policy.py`,
  `engine/dictionary.json`;
- provenance сборки/проверок, платформу, ожидаемые image IDs и решение о допуске.

**Export не включает launcher и документацию.** Передайте их отдельно из той же
согласованной версии scanner. Пользователю не нужны `src/`, `.git`, venv или
build context. Engine assets уже внутри scanner image; каталог `engine/` пакета
нужен для проверки переноса, а не для ручного монтирования в каждый scan.

Разместите launcher, например, в `/opt/ru-llm-scanner/scripts/docker_scanner.py`,
документацию рядом, пакет — в приватном каталоге ответственного оператора.
Создание `/opt`/`/srv` и владельцев выполняет администратор вне scanner;
runtime запускается **non-root**. Пример shell-путей:

```sh
cd /opt/ru-llm-scanner
PACKAGE=/srv/ru-llm-scanner/packages/cpu-arm64-approved
SCANNER_LOCK="$PACKAGE/deployment.json"
```

Пакет и установка защищаются от записи недоверенными jobs/разработчиками.
Не переносите реальные отчёты вместе с публичным комплектом. Образы могут
содержать внутренний словарь, поэтому весь пакет по умолчанию приватный.

## Импорт и verify

```sh
python3 scripts/docker_scanner.py import --directory "$PACKAGE"
python3 scripts/docker_scanner.py verify --deployment-lock "$SCANNER_LOCK"
```

Проверяйте код **каждой** команды: обе должны завершиться 0. При ошибке import
не продолжайте как при успешной установке. Import сверяет точный состав checksums
и SHA-256 до `docker load`, затем оба фактических platform IDs. Verify повторяет
проверку локальных образов. Сеть/pull для устранения отсутствующего образа не включается.

Путь `--deployment-lock` указан явно: без него launcher использует исторический
default относительно своего каталога, который может описывать другой image.
`import` берёт deployment из самого пакета; `--deployment-lock` ему не выбирает
другой комплект. Правила metadata/IDs/доверия — в [артефактах](../reference/artifacts.md).

Checksum-файл тоже должен поступить доверенно: цифровой подписи пакета нет.
Успешный import не доказывает безопасность неизвестного образа. Не редактируйте
lock вручную при несовпадении; выясните Docker store/платформу и происхождение.
На Docker 29/containerd reference может быть OCI index, а platform ID — отдельным
manifest; оба фиксируются проверенной сборкой.

## Контрольный snapshot

Это процедура проверки целевой установки, а не заявление, что данное руководство
уже пройдено на другом физическом offline host. На администраторском стенде нужен
Git для создания синтетического клона; обычному runtime launcher он на хосте не нужен.
Выберите **новый** доступный каталог; пример не содержит настоящих секретов:

```sh
CHECK_ROOT=/srv/ru-llm-scanner/install-check-001
mkdir -m 700 "$CHECK_ROOT"
git init "$CHECK_ROOT/repo"
git -C "$CHECK_ROOT/repo" config user.name 'Scanner installation check'
git -C "$CHECK_ROOT/repo" config user.email 'scanner@example.invalid'
git -C "$CHECK_ROOT/repo" config commit.gpgsign false
git -C "$CHECK_ROOT/repo" config core.hooksPath /dev/null
printf 'ordinary build notes\n' > "$CHECK_ROOT/repo/README.txt"
git -C "$CHECK_ROOT/repo" add README.txt
git -C "$CHECK_ROOT/repo" commit -m 'Synthetic installation fixture'

python3 scripts/docker_scanner.py snapshot \
  --deployment-lock "$SCANNER_LOCK" --repo "$CHECK_ROOT/repo" \
  --commit HEAD --output "$CHECK_ROOT/snapshot"
SCAN_EXIT=$?
printf 'scanner exit: %s\n' "$SCAN_EXIT"
```

Для этой простой контрольной фикстуры ожидается 0. Убедитесь, что:

- результат процесса 0, оба обычных отчёта существуют и принадлежат оператору;
- output приватный, файлы `0600`, нет ошибок в report и указан выбранный профиль;
- `coverage.complete=true`, `assurance=snapshot_verified`, файл обработан;
- клон/его конфигурация не изменились, контейнеры и сеть собственного project удалены.

Код 1 требует разбора конкретной находки, код 2 — [диагностики](operations.md).
Эта малая проверка не заменяет оценку качества/ёмкости/изоляции на целевом стенде.
Проверку находок выполняйте только синтетическими данными по согласованной
приёмочной матрице, не действующим ключом.

## Передача и хранение

В [чеклисте передачи](README.md#проверка-установки-и-передача-пользователю)
зафиксируйте установку, lock, доступ Docker к путям, output parent, config/baseline
roots и контакты оператора. Дайте пользователю явную команду verify с этим lock.
Решите, кто допускает clean baseline и кто удаляет отчёты из CI/backups.

Сохраните доверенный пакет, provenance, точный прежний deployment и images
на случай восстановления. Не удаляйте единственную рабочую копию ради проверки
import. Новый кандидат прошёл import/control в отдельном пустом Docker/containerd store
на нативных AMD64 и ARM64 ([протоколы](../../verification/linux-amd64/README.md));
[имеющиеся свидетельства](../../verification/README.md) не заявляют испытание
другого физического закрытого хоста.
