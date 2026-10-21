# Сборка собственного CPU комплекта

Выберите профиль, совпадающий с архитектурой нативного Docker daemon.
Готовый [v0.2.0](releases.md) содержит AMD64 и ARM64; собственная сборка для
его установки не требуется. v0.1.0 содержит только ARM64. Для AMD64 см.
[серверный профиль](linux-amd64.md); [результаты приёмки версии](../../verification/release-v0.2.0/README.md)
отделены от исторического [этапа #33](https://github.com/vovkins/ru-llm-scanner/issues/33).

| Docker server | `BUILD_PROFILE` | Artifact lock |
| --- | --- | --- |
| Linux aarch64 / arm64 | `cpu-linux-arm64` | `locks/offline-cpu-linux-arm64.artifacts.json` |
| Linux x86_64 / amd64 | `cpu-linux-amd64` | `locks/offline-cpu-linux-amd64.artifacts.json` |

Это путь администратора с исходниками. Для готового комплекта используйте
[установку из пакета](installation.md). Сборка/установка dependencies может
обращаться к одобренным источникам; сканирование готовыми images работает offline.
Нативные build/seal/повторная offline-сборка обоих профилей подтверждены в
[протоколах AMD64/ARM64](../../verification/linux-amd64/README.md).
Итоговый статус установки и эксплуатации указан там же; история ниже относится
к прежнему ARM64 комплекту.
На source checkpoint `2588571` полный новый offline-маршрут выполнен в отдельном
каталоге из `git archive`, с новым venv и единым runtime/deployment:
[evidence #24](../../verification/operations-dependencies/README.md).
Использовались локальный base, проверенный hash-cache и BuildKit cache;
это не cache-free сборка. [Исторический маршрут](../../verification/operations-stage-4/README.md)
относится к прежней recipe; его locks с новой сборкой не смешиваются.

## 1. Подготовить инструменты и отдельные пути

В доверенном checkout scanner нужны Python 3.11+, Git, Docker/Compose с BuildKit,
доступ к закреплённому base, upstream и источникам Python/OS packages/NER-модели.
Выполняйте команды последовательно в одной POSIX shell-сессии. При любом отказе
остановитесь и выясните причину; следующая команда не делает предыдущую успешной.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip==26.2.1
.venv/bin/python -m pip install -e . -r requirements-dev.txt
mkdir -p .build

BUILD_PROFILE=cpu-linux-arm64
BUILD_ROOT="$PWD/.build/$BUILD_PROFILE-build-001"
mkdir -m 700 "$BUILD_ROOT"
ANALYZER_CONTEXT="$BUILD_ROOT/analyzer"
SOURCE_CONTEXT="$BUILD_ROOT/analyzer-source"
ARTIFACT_CACHE="$PWD/.build/artifact-cache"
mkdir -p "$ARTIFACT_CACHE"
RUNTIME_LOCK="$BUILD_ROOT/analyzer.runtime.lock.json"
ENGINE_DIR="$BUILD_ROOT/engine"
SCANNER_CONTEXT="$BUILD_ROOT/scanner-context"
DEPLOYMENT="$BUILD_ROOT/deployment.json"
ANALYZER_TAG="ru-llm-scanner-analyzer:$BUILD_PROFILE-build-001"
SCANNER_TAG="ru-llm-scanner:$BUILD_PROFILE-build-001"
```

Для AMD64 замените только первую строку выбора на `BUILD_PROFILE=cpu-linux-amd64`
до создания каталогов. Не смешивайте contexts, wheels, runtime/engine/deployment
двух профилей. Нужен BuildKit с Dockerfile frontend 1.14+ для нормализации прав
`COPY --chmod`; нативные проверки закрепляют Docker 29.6.1.

`python3.11` можно заменить доступным Python 3.11+. Для каждого нового комплекта
выбирайте новые каталог и tags. Context/engine/lock outputs не перезаписываются;
не удаляйте старые рабочие артефакты автоматически. Пути с запятой не подходят
для preparation `--mount`; runtime Compose обрабатывает их отдельно.

Установка dev dependencies/build backend использует доверенную pip-конфигурацию
хоста. Отдельно обеспечьте загрузку **закреплённого** Python base из build profile
через одобренный канал. Не подменяйте digest текущим `python:latest`.
Если подготовка выполняется с сетью, загрузите base выбранного профиля явно:

```sh
BASE_IMAGE=$(.venv/bin/python -c 'import json,sys; print(json.load(open("upstream.lock.json"))["build_profiles"][sys.argv[1]]["base_image"])' "$BUILD_PROFILE")
docker pull --platform "linux/${BUILD_PROFILE#cpu-linux-}" "$BASE_IMAGE"
```

В закрытой среде вместо pull импортируйте заранее сохранённый и проверенный base
через доверенный канал. Наличие tar с произвольным tag не заменяет совпадение digest.

## 2. Подготовить закреплённый upstream

Из заранее подготовленного локального клона proxy:

```sh
.venv/bin/python scripts/analyzer.py prepare \
  --source /trusted/ru-llm-proxy --output "$SOURCE_CONTEXT" \
  --profile "$BUILD_PROFILE"
.venv/bin/python scripts/analyzer.py verify-context --context "$SOURCE_CONTEXT"
```

Альтернатива **только вместо** первой команды — явный fetch закреплённого SHA:

```sh
.venv/bin/python scripts/analyzer.py prepare --fetch \
  --output "$SOURCE_CONTEXT" --profile "$BUILD_PROFILE"
```

После альтернативы также выполните `verify-context`. `--fetch` — действие подготовки,
не скрытая возможность scan. `--source` читает tracked Git bytes указанного в
source lock коммита; рабочие изменения, соседние config/secrets/tmp и `.env`
вне export-list не копируются. Патчи применяются строго по before/after hashes,
без fuzz. Manifest фиксирует разрешённые inputs.

Upstream source, model revision/files, constraints и spaCy pins задаёт
[source lock](../../upstream.lock.json). Отдельный
artifact lock выбранного профиля из таблицы выше содержит
полный closure wheels, Debian-пакетов и прежней модели: URL, размер, SHA-256 и
назначение для Analyzer/scanner/tests. Подготовьте полный контекст:

```sh
.venv/bin/python scripts/prepare_offline_analyzer.py \
  --context "$SOURCE_CONTEXT" --output "$ANALYZER_CONTEXT" \
  --cache "$ARTIFACT_CACHE" --download
.venv/bin/python scripts/analyzer.py verify-context --context "$ANALYZER_CONTEXT"
```

Только `--download` разрешает получение отсутствующих artifacts из сети.
Для повторной подготовки из полного cache уберите этот флаг: отсутствующий или
повреждённый файл вызывает отказ. Cache содержит файлы, названные их SHA-256;
его можно заранее заполнить идентичными проверенными bytes через одобренный
канал. Модель не берётся из сканируемого клона. Итоговые bytes проверяет seal.
[Происхождение](../reference/detection.md).

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

Текущий CPU `build` требует полный offline context и использует закреплённый
`docker/analyzer-offline.Dockerfile` с `--network none --pull=false`. Wheels
устанавливаются с `--no-index --no-deps` в чистый package tree; `.deb` также
закреплены. BuildKit может проверять metadata базового digest в registry:
`--network none` ограничивает RUN, а не resolver FROM. Сохраните base локально
и проверьте поведение своего builder в изолированной среде.
`seal` без внешней сети проверяет реальные sources,
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
  --profile "$BUILD_PROFILE" \
  --engine-dir "$ENGINE_DIR" \
  --wheel "$BUILD_ROOT/wheels/ru_llm_scanner-0.1.0-py3-none-any.whl" \
  --context "$SCANNER_CONTEXT" --artifact-cache "$ARTIFACT_CACHE" \
  --download-artifacts
```

Версия wheel в примере соответствует текущему `pyproject.toml`; после согласованного
изменения версии выберите точный собранный файл. Engine exporter копирует только
source/runtime locks и закреплённые dictionary policy/rules, не модель и не код
проверяемого репозитория.

`build_scanner.py prepare` проверяет тот же artifact lock и получает Git `.deb`,
OS fixes и полный scanner wheel closure из cache. Только `--download-artifacts`
разрешает загрузку отсутствующего artifact; уберите флаг для cache-only работы.
Context содержит Dockerfile, inventory helper, wheelhouse, artifact lock,
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
и выполняет `pip check`, проверку уникальности metadata и imported packaging,
help/version/engine validation. Затем фиксирует IDs обоих
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
готовых images. Новая подготовка не выбирает более свежие пакеты автоматически:
изменение closure требует reviewed lock/hashes. Источник может удалить старый
artifact; тогда сохраните/передайте идентичный hash-cache, не меняйте pin ради
загрузки. Побайтово одинаковый image ID
при любой пересборке/другом Docker store не обещается. Рабочий старый комплект
сохраняйте для [отката](updating-analyzer.md).

## Корпоративные mirrors, proxy и CA

Сетевое получение inputs теперь выполняется host Python до сборки. При
необходимости передайте доверенный CA только инструменту подготовки:

```sh
.venv/bin/python scripts/prepare_offline_analyzer.py \
  --context "$SOURCE_CONTEXT" --output "$ANALYZER_CONTEXT" \
  --cache "$ARTIFACT_CACHE" --download --ca /trusted/ca.pem
```

Это альтернатива соответствующей команде шага 2, не повтор в существующий context.
Для scanner prepare также поддержан `--ca`. HTTPS proxy настраивается штатным
окружением urllib; credentials не сохраняются в context/lock/image. Для закрытого
зеркала передайте заранее заполненный hash-cache. Старые `--pip-config` и
`--apt-config` при новой pinned подготовке отклоняются; содержимое конфигураций
не копируется и не читается. `prepare --certs-dir` относится к исторической
upstream recipe, текущему offline CPU runtime CA для внешней сети не нужен.
TLS verify не отключайте. Настройка host pip для
wheel/dev dependencies выполняется отдельно без credentials в CLI URL/логах.
Конкретный корпоративный PKI/mirror этим руководством не объявляется проверенным.

## Другие платформы

Текущий production builder предназначен для CPU ARM64. GPU targets upstream
сохранены, но для CUDA/AMD64 нужны собственные закреплённые constraints/base/spaCy,
измеренный runtime, deployment и реальная приёмка. CPU lock не применяют к GPU;
скрытого fallback GPU→CPU нет. [Подробности](../analyzer.md#платформы-и-диагностика).
