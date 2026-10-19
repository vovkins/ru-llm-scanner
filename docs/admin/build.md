# Сборка собственного CPU ARM64 комплекта

Это путь администратора с исходниками. Для готового комплекта используйте
[установку из пакета](installation.md). Сборка/установка dependencies может
обращаться к одобренным источникам; сканирование готовыми images работает offline.
Проверены CPU Linux ARM64 и [указанная среда](README.md#среда-и-ответственность).
На `755152b` полный маршрут выполнен в новом каталоге с отдельным venv и единым
новым runtime/deployment: [evidence](../../verification/operations-stage-4/README.md).
Локальные base и BuildKit cache использовались; это не cache-free сборка.

## 1. Подготовить инструменты и отдельные пути

В доверенном checkout scanner нужны Python 3.11+, Git, Docker/Compose с BuildKit,
доступ к закреплённому base, upstream и источникам Python/OS packages/NER-модели.
Выполняйте команды последовательно в одной POSIX shell-сессии. При любом отказе
остановитесь и выясните причину; следующая команда не делает предыдущую успешной.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -e . -r requirements-dev.txt
mkdir -p .build

BUILD_ROOT="$PWD/.build/cpu-arm64-build-001"
mkdir -m 700 "$BUILD_ROOT"
ANALYZER_CONTEXT="$BUILD_ROOT/analyzer"
RUNTIME_LOCK="$BUILD_ROOT/analyzer.runtime.lock.json"
ENGINE_DIR="$BUILD_ROOT/engine"
SCANNER_CONTEXT="$BUILD_ROOT/scanner-context"
DEPLOYMENT="$BUILD_ROOT/deployment.json"
ANALYZER_TAG=ru-llm-scanner-analyzer:cpu-build-001
SCANNER_TAG=ru-llm-scanner:cpu-build-001
```

`python3.11` можно заменить доступным Python 3.11+. Для каждого нового комплекта
выбирайте новые каталог и tags. Context/engine/lock outputs не перезаписываются;
не удаляйте старые рабочие артефакты автоматически. Пути с запятой не подходят
для preparation `--mount`; runtime Compose обрабатывает их отдельно.

Установка dev dependencies/build backend использует доверенную pip-конфигурацию
хоста. Отдельно обеспечьте загрузку **закреплённого** Python base из build profile
через одобренный канал. Не подменяйте digest текущим `python:latest`.

## 2. Подготовить закреплённый upstream

Из заранее подготовленного локального клона proxy:

```sh
.venv/bin/python scripts/analyzer.py prepare \
  --source /trusted/ru-llm-proxy --output "$ANALYZER_CONTEXT" \
  --profile cpu-linux-arm64
.venv/bin/python scripts/analyzer.py verify-context --context "$ANALYZER_CONTEXT"
```

Альтернатива **только вместо** первой команды — явный fetch закреплённого SHA:

```sh
.venv/bin/python scripts/analyzer.py prepare --fetch \
  --output "$ANALYZER_CONTEXT" --profile cpu-linux-arm64
```

После альтернативы также выполните `verify-context`. `--fetch` — действие подготовки,
не скрытая возможность scan. `--source` читает tracked Git bytes указанного в
source lock коммита; рабочие изменения, соседние config/secrets/tmp и `.env`
вне export-list не копируются. Патчи применяются строго по before/after hashes,
без fuzz. Manifest фиксирует разрешённые inputs.

Upstream source, model revision/files, constraints и spaCy pins задаёт
[source lock](../../upstream.lock.json). Веса NER загружаются штатной стадией
сборки Analyzer по закреплённому model manifest, а не берутся из сканируемого
клона. Окончательные bytes/версии проверяет seal. [Происхождение](../reference/detection.md).

## 3. Собрать Analyzer и измерить именно этот image

```sh
.venv/bin/python scripts/analyzer.py build \
  --context "$ANALYZER_CONTEXT" --tag "$ANALYZER_TAG"
.venv/bin/python scripts/analyzer.py seal \
  --context "$ANALYZER_CONTEXT" --image "$ANALYZER_TAG" \
  --output "$RUNTIME_LOCK"
.venv/bin/python scripts/check_analyzer_integration.py \
  --context "$ANALYZER_CONTEXT" --runtime-lock "$RUNTIME_LOCK" \
  --output-dir "$BUILD_ROOT/analyzer-parity"
```

`build` может скачивать pinned packages/модель и использует upstream Dockerfile
с ограниченными адаптациями. `seal` без внешней сети проверяет реальные sources,
model files, spaCy, packages, настройки, context labels и platform/reference IDs.
При несоответствии финальный lock не принимается. Parity проверяет raw/patched NER
и словарь в curated workspace без сети; это отдельная проверка, не замена seal.
Host parity запускается non-root. [Подробности dev-проверок](../analyzer.md).

**Далее везде используется `$RUNTIME_LOCK`, полученный этой командой seal.**
`locks/analyzer-cpu-linux-arm64.runtime.lock.json` из Git описывает прежнюю локальную
сборку и не выбирается автоматически для нового image. Нельзя переписать его ID
или заменить им результат неудачного seal ради прохождения проверки.

## 4. Подготовить engine и scanner dependencies

```sh
.venv/bin/python scripts/prepare_scan_engine.py \
  --context "$ANALYZER_CONTEXT" --runtime-lock "$RUNTIME_LOCK" \
  --output "$ENGINE_DIR"
.venv/bin/python -m pip wheel --no-deps . --wheel-dir "$BUILD_ROOT/wheels"
.venv/bin/python scripts/build_scanner.py prepare \
  --engine-dir "$ENGINE_DIR" \
  --wheel "$BUILD_ROOT/wheels/ru_llm_scanner-0.1.0.dev0-py3-none-any.whl" \
  --context "$SCANNER_CONTEXT"
```

Версия wheel в примере соответствует текущему `pyproject.toml`; после согласованного
изменения версии выберите точный собранный файл. Engine exporter копирует только
source/runtime locks и закреплённые dictionary policy/rules, не модель и не код
проверяемого репозитория.

`build_scanner.py prepare` — online-фаза: disposable контейнер получает Git `.deb`
и полный pinned Python wheel closure. Нужен локальный точный Python base; сетевой
доступ/зеркала настраивает оператор. Context содержит только Dockerfile, wheelhouse,
`.deb`, четыре engine assets и inventory SHA-256. Нет `.git`, `.env`, соседнего
checkout, пользовательских отчётов или credentials. Не используйте build context `.`.

## 5. Offline build и проверка нового deployment

```sh
.venv/bin/python scripts/build_scanner.py build \
  --context "$SCANNER_CONTEXT" --tag "$SCANNER_TAG" \
  --deployment-lock "$DEPLOYMENT"
python3 scripts/docker_scanner.py verify --deployment-lock "$DEPLOYMENT"
.venv/bin/python scripts/check_cli_integration.py \
  --context "$ANALYZER_CONTEXT" --runtime-lock "$RUNTIME_LOCK" \
  --scanner-image "$SCANNER_TAG" --output-dir "$BUILD_ROOT/cli-verification"
.venv/bin/python scripts/check_acceptance.py \
  --deployment-lock "$DEPLOYMENT" --output-dir "$BUILD_ROOT/acceptance"
```

Сборка сверяет состав/hash context и текущий Dockerfile, требует локальный base,
вызывает `--pull=false --network none`, устанавливает wheels с `--no-index --no-deps`
и выполняет `pip check`, help/version/engine validation. Затем фиксирует IDs обоих
images и inventory в **новом** deployment. CLI integration использует тот же runtime
lock и проверяет установленный wheel; production acceptance использует новый deployment.

Не заменяйте source/runtime/deployment locks в Git и действующий комплект одним
фактом успешной сборки. Оцените реальные результаты, independent quality, notices
и целевую среду, затем отдельно примите комплект по процессу организации.
Изменённый image/profile требует нового snapshot вместо прежнего baseline.

## 6. Export и передача

```sh
python3 scripts/docker_scanner.py export --deployment-lock "$DEPLOYMENT" \
  --directory "$BUILD_ROOT/offline-package"
```

Пакет содержит точные `docker save` reference IDs, deployment, engine и checksums.
Engine извлекается из проверенного scanner image и сверяется с inventory.
Передайте пакет по доверенному каналу вместе с launcher/документацией из согласованной
версии. На закрытом хосте следуйте [импорту и проверке установки](installation.md);
путь `SCANNER_LOCK` там указывает на **deployment этого пакета**.

Для повторной offline-сборки сохраните точный context и base; для runtime достаточно
готовых images. Свежая online-подготовка Debian/Python может дать другой closure
или метаданные: inventory делает разницу проверяемой, но побайтово одинаковый ID
при любой пересборке/другом Docker store не обещается. Рабочий старый комплект
сохраняйте для [отката](updating-analyzer.md).

## Корпоративные mirrors, proxy и CA

Для **Analyzer** `prepare --certs-dir /trusted/ca` копирует верхнеуровневые `*.crt`
в manifest; ссылки не принимаются. Сертификаты попадут в prepared context/image
по upstream recipe — проверьте их назначение и допустимость распространения.
Соседняя папка certs автоматически не читается. `build --build-arg NAME` берёт
явно разрешённую настройку из окружения Docker; список — в [справочнике артефактов](../reference/artifacts.md).
Не передавайте credentials в build args: upstream Docker/pip может вывести их в лог.

Для **scanner prepare** используйте при необходимости:

```sh
.venv/bin/python scripts/build_scanner.py prepare \
  --engine-dir "$ENGINE_DIR" \
  --wheel "$BUILD_ROOT/wheels/ru_llm_scanner-0.1.0.dev0-py3-none-any.whl" \
  --context "$SCANNER_CONTEXT" \
  --pip-config /trusted/pip.conf --apt-config /trusted/apt.conf --ca /trusted/ca.pem
```

Это альтернатива команде prepare шага 4, а не повтор в существующий context.
Файлы монтируются read-only в `/run/secrets` только контейнера подготовки,
не передаются build args и не копируются в scanner context/image. CA применяется
через PIP_CERT/APT HTTPS CaInfo. TLS verify не отключайте. Настройка host pip для
wheel/dev dependencies выполняется отдельно без credentials в CLI URL/логах.
Конкретный корпоративный PKI/mirror этим руководством не объявляется проверенным.

## Другие платформы

Текущий production builder предназначен для CPU ARM64. GPU targets upstream
сохранены, но для CUDA/AMD64 нужны собственные закреплённые constraints/base/spaCy,
измеренный runtime, deployment и реальная приёмка. CPU lock не применяют к GPU;
скрытого fallback GPU→CPU нет. [Подробности](../analyzer.md#платформы-и-диагностика).
