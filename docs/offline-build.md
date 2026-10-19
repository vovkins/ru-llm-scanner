# Сборка и перенос в закрытую среду

Подготовка может обращаться к одобренным источникам пакетов/модели. Сканирование
из готовых образов работает локально и ничего не устанавливает/не скачивает.
Проверен профиль **CPU Linux ARM64**. Deployment lock — доверенный результат
сборки, не подпись издателя и не подтверждение безопасности произвольного образа.

## Подготовка Analyzer и engine

Соберите/seal Analyzer по [руководству](analyzer.md). Для текущей проверенной
версии используется существующий sealed образ с platform ID из
`locks/analyzer-cpu-linux-arm64.runtime.lock.json`; детекторы не изменены.
Базовый Python image должен уже присутствовать локально на машине подготовки.

```bash
python3 scripts/prepare_scan_engine.py \
  --context .build/analyzer \
  --runtime-lock locks/analyzer-cpu-linux-arm64.runtime.lock.json \
  --output .build/production-engine
```

Эта dev-команда требует установленного проекта и runtime-зависимостей на хосте.
Она копирует только source/runtime locks и закреплённые policy/rules. Это
доверенные assets; Python policy не берётся из проверяемого репозитория.

## Минимальный scanner context

В окружении разработки с Python 3.11+:

```bash
python3 -m pip wheel --no-deps . --wheel-dir .build/production-wheels

python3 scripts/build_scanner.py prepare \
  --engine-dir .build/production-engine \
  --wheel .build/production-wheels/ru_llm_scanner-0.1.0.dev0-py3-none-any.whl \
  --context .build/production-context

python3 scripts/build_scanner.py build \
  --context .build/production-context --tag ru-llm-scanner:cpu-local \
  --deployment-lock .build/production-deployment.json

python3 scripts/docker_scanner.py verify \
  --deployment-lock .build/production-deployment.json
```

Родительские каталоги должны существовать; context, engine output и новый
deployment lock не перезаписываются. `prepare` — отдельная online-фаза: disposable
контейнер скачивает Git .deb и полный pinned Python wheel closure. Build получает
только Dockerfile, wheelhouse, .deb, четыре engine assets и inventory с SHA-256.
Исходники клона, `.git`, `.env`, secrets и модель не попадают в scanner context.
Не запускайте build с контекстом `.` из корня проекта.

Python base закреплён digest, Git — версией, Python closure — версиями в
[requirements](../locks/requirements-scanner-linux-arm64.txt). Фактически полученные
.deb/wheels полностью хешируются в inventory/deployment. `build` сверяет состав,
хеши и текущий Dockerfile, требует локальный base до вызова BuildKit,
выполняет Docker build с `--pull=false --network none`, pip
`--no-index --no-deps` и `pip check`, затем offline help/version/engine validation.
Обновление Debian mirror может менять closure: новая подготовка даёт новый
reviewable inventory. Байтовая воспроизводимость свежей online-подготовки или
Image ID на другом Docker store не обещается. Для повторной offline-сборки
сохраните точный проверенный context и base image. Runtime переносит готовые образы.

## Корпоративные источники и сертификаты

`prepare` принимает `--pip-config /trusted/pip.conf`, `--apt-config /trusted/apt.conf`
и `--ca /trusted/ca.pem`. Файлы монтируются read-only в `/run/secrets` только
контейнера подготовки. Настройки mirror/proxy/credentials находятся внутри этих
файлов; значения не передаются build args, не печатаются и не копируются в context/
image. CA применяется через PIP_CERT и APT HTTPS CaInfo. Не отключайте TLS verify.
Файлы принадлежат оператору, не проверяемому проекту; `.env`, config/secrets
соседнего proxy автоматически не читаются. Пути подготовки с запятой явно
отвергаются из-за синтаксиса Docker `--mount`; runtime Compose поддерживает их.

Установку build backend для wheel отдельно настраивает оператор через безопасную
конфигурацию pip. Credentials в URL командной строки/логах недопустимы.
Механизм secret mounts реализован; конкретный корпоративный PKI/proxy/mirror
не воспроизведён на данном стенде и требует проверки владельцем.

## Offline export / import

```bash
python3 scripts/docker_scanner.py export \
  --deployment-lock .build/production-deployment.json \
  --directory /transfer/scanner-cpu-arm64

# Перенесите каталог по доверенному каналу; затем на закрытом хосте:
python3 scripts/docker_scanner.py import --directory /transfer/scanner-cpu-arm64

python3 scripts/docker_scanner.py snapshot \
  --deployment-lock /transfer/scanner-cpu-arm64/deployment.json \
  --repo /data/project --commit HEAD --output /data/results/initial
```

Export использует `docker save` точных reference IDs; пакет содержит `images.tar`,
`deployment.json`, четыре engine файла и `checksums.json`. Engine извлекается
только из проверенного scanner image и сверяется с build inventory. Import
проверяет точный список/SHA-256 до `docker load`, затем фактические platform
IDs обоих образов. Один tar hash или mutable tag не подтверждает поведение.
Checksum manifest сам поступает по доверенному каналу: цифровой подписи нет.
Не импортируйте недоверенные tar/locks. Полный пакет приватный, образы могут
содержать корпоративный словарь; не публикуйте его автоматически.

Save/load проверен в доступном локальном Docker store без удаления единственной
рабочей копии; это не испытание физически отдельного закрытого хоста. Registry
не использовался. ARM64 не запускается как подтверждённый AMD64-профиль.
На Docker 29/containerd reference может быть OCI index ID, а поведение проверяется
по platform manifest ID. При несовпадении import/scan возвращает 2; не заменяйте
ожидаемый ID вручную без новой проверенной сборки/seal/приёмки.

## GPU

Исходный механизм сохраняет upstream GPU targets/profiles и отдельные constraints:
см. [Analyzer](analyzer.md) и [source lock](../upstream.lock.json). Нужны NVIDIA GPU,
совместимые CUDA/driver/container toolkit, отдельный образ и реальный seal/runtime
lock. Текущий production builder/launcher проверен и документирован для CPU ARM64;
GPU production deployment на этом стенде не подготовлен. Не используйте CPU lock
для GPU, не добавляйте неподтверждённый digest и не вводите fallback GPU→CPU.
Новый Analyzer ID/профиль требует нового полного snapshot, даже если API не изменился.
