# Релиз v0.2.0: Linux AMD64 и ARM64

Это инструкция к комплекту **v0.2.0**. Состояние публикации и точные assets — в
[GitHub Releases](https://github.com/vovkins/ru-llm-scanner/releases).
Поддержка обеих CPU-платформ находится в main; GPU в выпуск не входит.
[Прежний v0.1.0](releases-v0.1.0.md) остаётся отдельным ARM64-комплектом.

## Выбрать платформу и получить установку

Выбирайте архив по архитектуре **Docker server**, включая случай удалённого daemon.
Не переименовывайте locks и не смешивайте образы разных архитектур/версий.
Нужны Python3.11+, rootful Docker/Compose и non-root оператор с доступом к daemon.
[Проверенные стенды, ресурсы и ограничения](linux-amd64.md).

| Docker server | Архив |
| --- | --- |
| Linux x86_64 / amd64 | `ru-llm-scanner-v0.2.0-linux-amd64.tar.gz` |
| Linux aarch64 / arm64 | `ru-llm-scanner-v0.2.0-linux-arm64.tar.gz` |

Загрузите архив и `SHA256SUMS` из **одного** выпуска, проверьте полную SHA-256
до распаковки. Checksum подтверждает целостность, не личность издателя;
источник и доставка должны быть доверенными. На Linux:

```sh
sha256sum --check --ignore-missing SHA256SUMS
# Пример для AMD64; на ARM64 используйте соответствующее имя архива/каталога.
tar -xzf ru-llm-scanner-v0.2.0-linux-amd64.tar.gz
cd ru-llm-scanner-v0.2.0-linux-amd64
python3 -I -S scripts/docker_scanner.py import --directory package
python3 -I -S scripts/docker_scanner.py verify --deployment-lock package/deployment.json
```

На macOS доступна `shasum -a 256` для ручного сравнения той же записи.
Для закрытого контура перенесите проверенные архив и checksums доверенным каналом,
повторите проверку/import/verify на целевом узле. При scan нет pull/build/fetch;
модель и зависимости уже в images. Изолированный import/control проверяется
на native Linux обеих архитектур, целевой сервер требует собственного пилота.

Далее выполните [контрольный snapshot](installation.md#контрольный-snapshot).
Всегда передавайте `package/deployment.json` **этого** комплекта явно.
Исторические default locks в Git сохраняются для прежней эксплуатации.

## Состав поставки

| Артефакт | Назначение |
| --- | --- |
| Два `ru-llm-scanner-v0.2.0-linux-ARCH.tar.gz` | Launcher, docs/source, `package/images.tar`, engine/deployment/checksums и metadata |
| `release-manifest-amd64.json`, `release-manifest-arm64.json` | SHA-256 состава соответствующего архива, platform/image/source identities; копия manifest внутри архива |
| `ru_llm_scanner-0.2.0-py3-none-any.whl` | Python CLI для разработки; отдельно не содержит Analyzer/модель |
| `ru-llm-scanner-v0.2.0-native-sources.tar.gz` | Соответствующие native sources обеих платформ при подтверждённом совпадении closure |
| `registry-images.json` | Общие index digests, platform manifests и соответствие проверенным images |
| `SHA256SUMS` | Полные hashes отдельных assets |

В `metadata/verification` находятся безопасные протоколы конкретной платформы;
в `metadata/wheels` — wheel именно этой сборки. `upstream-source/` содержит
curated patched Analyzer/словарь; notices/licenses включены. Raw отчётов,
credentials, build-cache и host configs в архиве нет.

## Образы GHCR

Два публичных packages: `ghcr.io/vovkins/ru-llm-scanner` и
`ghcr.io/vovkins/ru-llm-scanner-analyzer`. У каждого:

- `0.2.0` — общий OCI index Linux AMD64/ARM64;
- `0.2.0-amd64`, `0.2.0-arm64` — проверенные платформенные сборки.

```sh
docker pull ghcr.io/vovkins/ru-llm-scanner:0.2.0
docker pull ghcr.io/vovkins/ru-llm-scanner-analyzer:0.2.0
```

Общий tag выбирает архитектуру daemon. Для воспроизводимого получения используйте
index/child `@sha256:…` из registry receipt. Общий index digest, platform manifest
и config ID — разные сущности; не подставляйте общий index вместо platform ID
в sealed engine/runtime/deployment. Один pull не устанавливает launcher/locks.
Штатная offline установка использует проверенный пакет целиком: import восстанавливает
исходные reference IDs; соответствие platform manifests опубликованным bytes
проверяется отдельно. Версия0.1.0 и её digests остаются ARM64; `latest` не вводится.

## Обновление, baseline и откат

Version/image/source fingerprints v0.2.0 отличаются от v0.1.0: нужен новый полный
clean snapshot для baseline. Совпадение модели не делает старый baseline совместимым.
Сохраните старый каталог установки/пакет; новый разместите рядом, затем выполните
verify и контрольный scan non-root учётной записью оператора/агента.
[Jenkins](jenkins.md) получает явный `SCANNER_DEPLOYMENT_LOCK` нового пакета из
доверенной конфигурации; входной проект его не выбирает.
Откат — выбор прежней установки/deployment **той же архитектуры**, без изменения старых
образов/locks. ARM64 v0.1.0 не является вариантом отката для AMD64.

Четыре native-риска и [решение о certifi/HTTPS](../../verification/linux-amd64/certifi-advisory.md)
сохранены; исправление библиотек не заявляется. Принят штатный offline Docker route
с внутренним HTTP Scanner→Analyzer; произвольный HTTPS raw CLI вне этого решения.

## Сопровождающему выпуска

[План #36](https://github.com/vovkins/ru-llm-scanner/issues/36) разрешает выпуск
после gates обеих платформ. Workflow `build-release.yml` вызывается из существующего `check-cpu-platforms.yml`
с `release_version=0.2.0` и `source_revision` (без registry write), либо напрямую
после регистрации GitHub API. Сборка запускается на
точном согласованном main SHA: native builds/tests → fresh-store control →
реальный Jenkins AMD64 → полный Requests → inventories/advisories → frozen draft assets.
Images на disposable runner сохраняются в этих архивах; обычные CI artifacts
содержат только безопасные summaries, без images/model/cache/raw reports.

После сохранения финальных `.tar.gz` тот же verification workflow с
`verify_frozen=true` и обоими настоящими hashes вызывает проверочный
`verify-frozen-release.yml`: архивы скачиваются, извлекаются и проходят import/control
в отдельных пустых Docker/containerd stores обеих платформ.
Для чтения ещё скрытых draft assets этим jobs требуется `contents: write`
по ACL GitHub; операции остаются download/verify, `packages: write` им не выдаётся.
Проверка уже публичных assets использует read-only token и anonymous download.
Перед публикацией `release-acceptance.json` связывает успешный build workflow,
оба archive hashes и завершённый разбор advisory без новых blockers. Publisher
проверяет эту запись и реальный success соответствующего native workflow.
`publish-release.yml` получает явные version/source SHA и hashes двух архивов,
импортирует и проверяет **те же** images, отправляет platform tags и формирует
общие indexes по проверенным child digests. Используется временный GITHUB_TOKEN;
registry write есть только в publish jobs, PR runs не получают write-прав.
Существующий versioned tag не заменяется другим содержимым; auth/transport error
не считается отсутствием. Повтор продолжает тот же frozen комплект.

GitHub Release остаётся draft до успешных проверок всего комплекта и анонимных
GHCR pull/control. Общей транзакции двух packages/tags нет: частичная публикация
не означает успешный выпуск. После обычной публикации `publish-release.yml` с `mode=verify-public` вызывает
read-only reusable `verify-release.yml`: он
скачивает assets без credentials, проверяет полные hashes и installed control
на обеих native платформах. Новый tag/asset не переиспользуется для другой сборки.
[Протоколы выпуска](../../verification/release-v0.2.0/README.md).
