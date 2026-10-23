# Релиз v0.3.0: простой запуск и обновлённый Analyzer

Выпуск готовится по согласованному [плану #51](https://github.com/vovkins/ru-llm-scanner/issues/51).
До завершения публичных проверок это кандидат, а не опубликованная поставка.
[Протокол и состояние](../../verification/release-v0.3.0/README.md).
Прежние инструкции: [v0.2.0 AMD64/ARM64](releases-v0.2.0.md),
[v0.1.0 ARM64](releases-v0.1.0.md).

## Обычный запуск из Git

Основной путь — доверенный checkout версии проекта на сервере с интернетом:

```sh
git clone --branch v0.3.0 --depth 1 https://github.com/vovkins/ru-llm-scanner.git
cd ru-llm-scanner
make build
make test
make scan REPO='/srv/git/example project'
```

Используйте этот тег после публикации. Нужны Git, Python3.11+ с venv/make и
rootful Docker Engine API1.49+/Compose2; оператор non-root, архитектура Docker
server — Linux AMD64 или ARM64. `make build` сам готовит окружение, модель,
образы и проверяет готовность. Он **собирает из исходников**, а не устанавливает
образы из GHCR. После сборки scan/test не скачивают зависимости.
Ручной `deployment.json`, скачивание wheel и выбор image ID для этого пути не нужны.
Автоматические GitHub source ZIP без `.git` не являются проверенным Make-путём.

`make scan` проверяет tracked состояние HEAD. [Руководство пользователя](../user/README.md)
объясняет COMMIT, diff, CONFIG/OUTPUT и strict baseline. Код CLI — 0/1/2;
Make использует собственный код ошибки рецепта, поэтому для
[Jenkins](jenkins.md) используйте доверенный `scanner` напрямую.
Полные JSON/HTML отчёты приватные; найденные значения в них не маскируются.

## GHCR и полные архивы

Планируются два публичных package:

| Package | Общий OCI index | Платформенные tags |
| --- | --- | --- |
| `ghcr.io/vovkins/ru-llm-scanner` | `0.3.0` | `0.3.0-amd64`, `0.3.0-arm64` |
| `ghcr.io/vovkins/ru-llm-scanner-analyzer` | `0.3.0` | `0.3.0-amd64`, `0.3.0-arm64` |

Каждый index содержит ровно Linux AMD64 и ARM64. `latest` не вводится.
После публикации получить образы отдельно можно так:

```sh
docker pull ghcr.io/vovkins/ru-llm-scanner:0.3.0
docker pull ghcr.io/vovkins/ru-llm-scanner-analyzer:0.3.0
```

Pull сам по себе не устанавливает CLI и sealed engine/deployment. Полный
архив `ru-llm-scanner-v0.3.0-linux-ARCH.tar.gz` объединяет исходники/docs,
launcher и `package/images.tar`, locks/checksums, соответствующий wheel и receipts.
Версионные digests публикуются в `registry-images.json`; OCI index, платформенный
manifest и config ID различаются. Используйте соответствующий целый комплект.

Для расширенного переноса без сборки скачайте архив своей архитектуры и
`SHA256SUMS` из одного доверенного выпуска, проверьте **полную** SHA-256 до распаковки.
Пример для AMD64 на Linux:

```sh
sha256sum --check --ignore-missing SHA256SUMS
tar -xzf ru-llm-scanner-v0.3.0-linux-amd64.tar.gz
cd ru-llm-scanner-v0.3.0-linux-amd64
python3 -I -S scripts/docker_scanner.py import --directory package
python3 -I -S scripts/docker_scanner.py verify --deployment-lock package/deployment.json
```

Продолжение — [explicit installed control](installation.md#контрольный-snapshot)
с `package/deployment.json` этого архива. Это отдельный совместимый маршрут;
import не создаёт готовую Make-установку и не заменяет обычный Git quickstart.
Не переносите вместе с поставкой реальные отчёты или credentials.

## Обновление и откат

Analyzer закреплён на `9e47e6594ba3d9616ba90720994ced008335416c`, policy `logistic`,
API metadata v2. Модель, словарь, коэффициенты и зависимости сохраняются.
`rule_id` обозначает конкретное правило; одинаковые входы и конфигурация должны
давать одинаковые идентификаторы. Отсутствующий идентификатор допустим для
источника без отдельного правила. Это metadata находки, а не новый параметр запуска.

Baseline v0.2.0 несовместим с новым engine/profile. Сохраните старые установку,
образы и baseline; новый checkout разместите рядом, выполните build/test и новый
полный clean snapshot. Baseline не продвигается автоматически. Для отката выберите
прежнюю готовую установку и её baseline той же архитектуры; старые locks не правьте.
Процедура [обновления Analyzer](updating-analyzer.md) сохраняется.

Измеренные до релиза ограничения: code-v1 33TP/14FP/4FN; малые Base64-примеры
11/3/1. Повторение2500 элементов — нагрузочный сценарий, не независимая выборка.
Logistic может отмечать Base64 с обычным содержимым. [Оценка качества](../reference/detection.md)
и [решение по NER-пересечению](../../verification/simple-workflow-stage-6/criterion-amendment.md)
сохраняются; финальные релизные измерения фиксируются отдельно.
Принятые [native-риски](../../verification/operations-dependencies/risk-acceptance.md)
и [certifi/HTTPS](../../verification/linux-amd64/certifi-advisory.md) не исправлены.

## Сопровождающему выпуска

Релизный PR сначала проходит unit/contracts/docs/format и native smoke обеих CPU.
После слияния фиксируется один main SHA. `build-release.yml` на этом SHA выполняет
буквальный Make walkthrough, экспортирует **его** образы и проверяет upstream,
реальную NER/качество/стабильность metadata, Requests, fault/capacity/rollback и
настоящий direct Jenkins AMD64. Legacy Jenkins проверяется отдельно.
Runtime images после этого не заменяются другой сборкой.

Архивы с safe receipts сохраняются в matching draft Release. Затем
`verify-frozen-release.yml` скачивает полные архивы и проверяет их в пустых
Docker/containerd stores обеих платформ. `release-acceptance.json` связывает
реальные successful runs, source, hashes и advisory disposition.

Только отдельный `publish-release.yml` с `packages:write` импортирует принятые
образы, отправляет четыре platform tags и два indexes. Версионный tag/asset с
другими bytes не перезаписывается; auth/network failure не считается отсутствием.
После анонимных native GHCR pull/control публикуется GitHub Release на тот же SHA,
затем повторяются public full-download/control и буквальный Git-tag quickstart.
Частичная публикация не равна успешному выпуску; повтор продолжает только тот же
frozen комплект. Последующие metadata commits не перемещают тег и не меняют images.
