# Linux AMD64: подготовка серверного комплекта

Поддержка реализуется в [#33](https://github.com/vovkins/ru-llm-scanner/issues/33).
Это инструкция к неопубликованному кандидату; опубликованный v0.1.0 остаётся
ARM64-релизом. Нативная AMD64 приёмка и настоящий Jenkins ещё выполняются:
[протоколы и статус](../../verification/linux-amd64/README.md).

## Выбор платформы

Цель — CPU Linux x86-64 (`linux/amd64` в Docker). Профиль
`cpu-linux-amd64` использует ту же upstream revision, модель, словарь и версии
Python/Debian dependencies, что ARM64 reference. Для каждого профиля закреплены
свои wheels/DEBs/base digest и отдельный runtime/deployment. GPU не требуется.

Испытательный стенд — нативный Ubuntu 24.04 x86-64 на AMD EPYC 7763 (4 vCPU,
AVX2/FMA), Docker 29.6.1 и Compose. Измеренные RAM/диск и результат Jenkins будут
внесены после проверки. NumPy 2.4 поднял стандартный x86 baseline до
[x86-64-v2](https://numpy.org/doc/stable/release/2.4.0-notes.html#modulate-dispatched-x86-cpu-features);
baseline фактического wheel и PyTorch capability дополнительно снимаются в runtime.
Для старого CPU или VM со скрытыми CPU flags требуется проверка целевого узла.
На Apple Silicon эмуляция пригодна для вспомогательной отладки; приёмка проходит
на нативном AMD64. Launcher проверяет архитектуру Docker **server**, включая
случай удалённого daemon, и возвращает `daemon_platform_mismatch` при несовпадении.

## Сборка

Следуйте [общему порядку сборки](build.md), выбирая на подготовке Analyzer
`--profile cpu-linux-amd64` и отдельные каталоги/tags для нового кандидата.
На `build_scanner.py prepare` также можно явно передать
`--profile cpu-linux-amd64`; без него используется профиль проверенного engine.
Несовпадение профилей Analyzer и Scanner вызывает отказ.

Сеть разрешается только на явной подготовке: `--fetch`, `--download` и
`--download-artifacts`. Далее используется полный hash-cache и локальный base.
`build --no-cache` доступен для Analyzer и Scanner и не меняет запрет сети для RUN.
Для неизвестной ошибки сборки Scanner доступен флаг `--diagnostics` **перед**
подкомандой: диагностика доверенных build inputs идёт в stderr.

Docker recipes нормализуют права копируемых файлов/каталогов с помощью
`COPY --chmod=u=rwX,go=rX`: restrictive umask подготовки не должен делать код,
модель или engine недоступными непривилегированному пользователю контейнера.
Нужен BuildKit с Dockerfile frontend 1.14+; нативный стенд закрепляет Docker 29.6.1.
Внешний frontend через mutable `# syntax` автоматически не скачивается.

## Установка, сканирование и baseline

Каждая архитектура получает отдельный offline-пакет с явным `deployment.json`.
Используйте [импорт и проверку установки](installation.md) и команды
[руководства пользователя](../user/README.md), передавая deployment **этого
пакета** через `--deployment-lock`. Нельзя переименовать ARM64 lock или заменить
только один image на AMD64. Импорт не означает подтверждения совместимости;
после него обязательны `verify` и контрольный scan.

Изменяется runtime/profile fingerprint, поэтому перед переходом к diff на AMD64
нужен новый полный чистый snapshot. Старый ARM64 baseline не следует переносить
как совместимый. JSON/HTML сохраняют полные значения; console содержит сводку.

Для Jenkins используйте [руководство интеграции](jenkins.md) и доверенный AMD64
пример с `SCANNER_DEPLOYMENT_LOCK`. Код примера берётся из установки scanner,
а входной Git-клон, configs и baselines располагаются вне очищаемого workspace.
Доступ к Docker и отчётам предоставляет администратор. Боевой Jenkins текущими
проверками не изменяется.

## Приёмка кандидата

Непубликующий `check-cpu-platforms.yml` выполняет нативные проверки обеих
архитектур. Сравниваются решения распознавания и покрытие; абсолютная погрешность
confidence до `1e-5` допускается только при совпадении категории/значения/spans/
источника и набора находок. Порог зафиксирован до получения AMD64 результатов.
Наблюдаемое расхождение решения не скрывается этой погрешностью.

В workflow разрешены только безопасные протоколы. Полные реальные отчёты Requests,
build cache, контейнерные images и credentials не публикуются как CI artifacts.
Слияние PR, следующий release/tag и GHCR push требуют отдельного указания владельца.
