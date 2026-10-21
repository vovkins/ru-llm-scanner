# Релиз v0.1.0: получение и проверка

Архивная инструкция неизменного ARM64 выпуска; [новая поставка v0.2.0](releases.md) описана отдельно.

Канал выпуска — [GitHub Releases](https://github.com/vovkins/ru-llm-scanner/releases/tag/v0.1.0),
образы — публичный GitHub Container Registry. Выпуск содержит **только Linux ARM64 CPU**.
AMD64/GPU образы не публикуются. Используйте offline-комплект: он связывает оба
образа, engine, locks и launcher, а также включает модель без скачивания при scan.

## Получить готовую установку

На машине с доступом к GitHub загрузите `SHA256SUMS` и
`ru-llm-scanner-v0.1.0-linux-arm64.tar.gz` из одного релиза. Проверьте SHA-256
архива по записи в SHA256SUMS **до распаковки**. Сверяйте источник загрузки:
checksum рядом с файлом не является независимой цифровой подписью.

```sh
sha256sum --check --ignore-missing SHA256SUMS
tar -xzf ru-llm-scanner-v0.1.0-linux-arm64.tar.gz
cd ru-llm-scanner-v0.1.0-linux-arm64
python3 -I -S scripts/docker_scanner.py import --directory package
python3 -I -S scripts/docker_scanner.py verify --deployment-lock package/deployment.json
```

На macOS доступна `shasum -a 256` для ручного сопоставления с той же записью.
`import` сначала сверяет внутренние hashes, затем загружает локальные images
и проверяет platform IDs. `verify` не строит и не скачивает образы.
Для переноса в закрытый контур передайте проверенный архив, SHA256SUMS и
доверенную запись об источнике; на целевой машине повторите проверку/import/verify.
Для сканирования сеть не требуется.

Нужны Python 3.11+, Docker с API 1.49+ и Compose v2+, non-root оператор и
достаточная память. Далее выполните [контрольный snapshot](installation.md#контрольный-snapshot)
и передайте пользователю явный путь `package/deployment.json`.
Не используйте исторический default lock в `locks/` для этого выпуска.

## Состав

| Артефакт | Назначение |
| --- | --- |
| `ru-llm-scanner-v0.1.0-linux-arm64.tar.gz` | Исходники установки, docs, launcher, package/images.tar, четыре engine assets и deployment/checksums |
| `ru-llm-scanner-v0.1.0-native-sources.tar.gz` | Соответствующие исходники Debian-пакетов образов и их manifest |
| `ru_llm_scanner-0.1.0-py3-none-any.whl` | Python CLI для dev/integration; сам по себе не содержит Analyzer/модель |
| `release-manifest.json` | Build revision, hashes входов и файлов комплекта, image IDs, версия/платформа |
| `registry-images.json` | Фактические GHCR digests и соответствующие локальные platform IDs |
| `SHA256SUMS` | Контрольные суммы отдельных release assets |

В основном архиве `metadata/` содержит runtime/deployment, license/native
inventories и сведения о происхождении; `upstream-source/` — curated patched
источники Analyzer/словаря. Raw пользовательских отчётов, credentials, host CA,
локальных proxy configs и build-cache в комплекте нет.

## GHCR

Два образа имеют теги `0.1.0`:

```sh
docker pull --platform linux/arm64 ghcr.io/vovkins/ru-llm-scanner:0.1.0
docker pull --platform linux/arm64 ghcr.io/vovkins/ru-llm-scanner-analyzer:0.1.0
```

Для воспроизводимого получения используйте `@sha256:…` из `registry-images.json`;
теги служат удобными именами. Один pull не устанавливает launcher/engine/lock.
GHCR digest описывает опубликованный manifest/index; platform image ID и
reference ID могут различаться. Готовый package/deployment.json сохраняет
проверенные ID, которые восстанавливает offline `import`.

## Сопровождающему выпуска

Задача [#31](https://github.com/vovkins/ru-llm-scanner/issues/31) фиксирует согласование
v0.1.0, MIT и публичных образов. Workflow `publish-release.yml` запускается вручную
на main с SHA-256 конкретного проверенного архива. Он загружает frozen draft asset,
сверяет hashes и исходники с checkout, импортирует **те же** образы на ARM64 runner,
выполняет installed verify/snapshot/strict diff/error, затем отправляет их в GHCR
через временный GITHUB_TOKEN. Повторной удалённой сборки нет.

Публикация требует `contents: write` и `packages: write` только этому job.
Не помещайте PAT в репозиторий или чат. После push отдельно проверьте публичную
видимость обоих packages и анонимный pull по digest; публичность репозитория
сама по себе её не задаёт. Финальные manifests/checksums и release публикуются
после этих проверок. Stable tags не перезаписываются новыми сборками.

Релиз сохраняет [известное качество и ограничения](../reference/detection.md)
и [принятое решение по четырём native-рискам](../../verification/operations-dependencies/risk-acceptance.md).
Для другого окружения проведите собственную приёмку. Возврат выполняется выбором
прежнего точного deployment; импорт нового комплекта не меняет старые locks.

Новые release image/source fingerprints требуют нового clean snapshot: старый baseline
не становится совместимым от одного совпадения модели и словаря.
