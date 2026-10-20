# Linux AMD64 — реализация и нативная приёмка

План [#33](https://github.com/vovkins/ru-llm-scanner/issues/33) явно согласован
2026-10-20. Исходная точка `9c062c8684cb1c7d907cbb08fc1a2f3fd4c33ca5`;
ветка `codex/linux-amd64`. Работа продолжается; готовность AMD64 пока не заявляется.
Слияние и публикация не разрешены.

## Проверено при подготовке

- Сохранены исходные hashes старых locks, корпуса/patches и идентичность семи
  работающих чужих контейнеров в приватном `.build/linux-amd64/baseline.json`.
- Локальный Docker 29.6.1 работает на Linux aarch64; нативный AMD64 gate выполняется
  отдельно, на GitHub runner `ubuntu-24.04`. Эмуляция не считается приёмкой.
- Официальные PyPI/PyTorch CPU и Debian indexes содержат все закреплённые версии:
  AMD64 artifact lock включает 132 записи, Python package closure и версии 33
  Debian-пакетов совпадают с ARM64. Все фактические bytes проверены по
  размеру/SHA-256, wheel tags/metadata/ELF и Debian control; ошибок нет.
- Принятая Python база `python@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce`
  является OCI index, а не только ARM64 manifest. Её AMD64 child
  `sha256:e529028263dbe6910a2d96f7d2b8f5266385e917fd45d286ef166977c094a51e`
  выбран явно; Python/OS family не обновлялись из mutable tag.
- Модель, исходники детекторов/словарь и patches/corpus не изменены. Изменение
  source lock/profile/image fingerprint означает новый baseline после установки.
- Начальные host unit-проверки: 167 tests, 0 failures/errors/skipped. Первый запуск
  внутри sandbox не смог открыть синтетический localhost HTTP server; полный
  повтор с разрешённым bind прошёл. Это ещё не нативная AMD64 интеграция.

## Карта изменений

`build_platforms.py` проверяет CPython ABI/platform tags, реальный ELF machine,
Debian control metadata; `offline_assets.py` применяет проверки до установки.
`build_scanner.py` выбирает профиль согласованного Analyzer engine, формирует
Dockerfile из pinned base и не принимает смешанные artifacts/runtime/platform.
Launcher сверяет архитектуру Docker server и отказывает при попытке незаметного
запуска чужой платформы. Jenkins adapter принимает доверенный абсолютный путь
`SCANNER_DEPLOYMENT_LOCK`; прежний режим без переменной сохранён.

`check-cpu-platforms.yml` предназначен для нативных проверок обеих архитектур.
Он не имеет permissions публикации packages/releases и сохраняет только
разрешённые сводки. Образы, полные отчёты, context/cache и логи не загружаются
в публичные CI artifacts. Исторический `publish-release.yml` не запускается.

## Нативные результаты

[Промежуточные протоколы](native-progress/provenance.json) сохраняют происхождение
каждого прогона; они не обозначают завершение всей приёмки.

| Проверка | Результат |
| --- | --- |
| Native AMD64 и ARM64 build/seal/verify/export | Пройдены, без build cache и с блокировкой root HTTP/HTTPS builder |
| Повторная cache-only подготовка и uncached build | Пройдены на обеих архитектурах, material inputs/runtime inventories совпали |
| Upstream core / NER | 478 / 96 на каждой архитектуре |
| NER / dictionary parity | 77 / 4 |
| Independent code-v1 | TP33 / FP13 / FN4; модель/порог/ожидания сохранены |
| [Native cross-platform NER](native-prediction-comparison.json) | Решения 77 случаев совпали; max confidence delta 2.265e-6 |
| [Published v0.1.0 ARM64 → AMD64](published-reference-comparison.json) | Решения совпали; max delta 1.609e-6 |
| [Настоящий Jenkins AMD64](native-progress/jenkins-native-amd64.json) | 13 сценариев, включая cancel/timeout/agent-loss recovery |
| Native source closure | 82 retained sources; фактические версии совпали на обеих архитектурах |
| Прежний system libstdc++ aligned-new exclusion | Повторно проверен вызов posix_memalign в ELF обеих архитектур; не распространяется на все static wheel paths |

## Оставшиеся проверки

Полный Requests с точной конфигурацией прежнего reference, все production/fault
gates и чистый image store, измерение ресурсов, финальная документация и контроль
комплекта. Исправляются ошибки Linux test harness, которые не были видны через
Docker Desktop bind mounts. Результаты фиксируются по факту; #33 остаётся открытой.
Новый [certifi advisory](certifi-advisory.md) и конкретное предложение #34 ожидают
решения владельца; прежнее принятие четырёх native-рисков этим не меняется.
