# Linux AMD64: подготовка серверного комплекта

Основная установка текущих исходников — [make build/test](build.md), сканирование — [Make/CLI](../user/README.md). Ниже сохранены CPU-ограничения, измерения и explicit-процедуры этапа #33/v0.2.0; они не нужны как ручные шаги нового первого запуска.

Поддержка включена в `main` через [PR #35](https://github.com/vovkins/ru-llm-scanner/pull/35);
[слияние и контроль main](../../verification/linux-amd64/main-integration/README.md)
проверены отдельно. [v0.2.0 опубликован](releases-v0.2.0.md) для AMD64/ARM64;
[приёмка релизных образов, GHCR и архивов](../../verification/release-v0.2.0/README.md)
прошла на обеих native платформах. v0.1.0 остаётся ARM64-релизом.
Ниже приведены также исходные измерения этапа [#33](../../verification/linux-amd64/README.md);
новые измерения v0.2.0 приведены отдельно в протоколах выпуска.

## Выбор платформы

Цель — CPU Linux x86-64 (`linux/amd64` в Docker). Профиль
`cpu-linux-amd64` использует ту же upstream revision, модель, словарь и версии
Python/Debian dependencies, что ARM64 reference. Для каждого профиля закреплены
свои wheels/DEBs/base digest и отдельный runtime/deployment. GPU не требуется.

Параметры сервера и Jenkins-агента пока не выбраны владельцем (2026-10-21).
Опорный испытательный стенд — нативный Ubuntu 24.04 x86-64 в GitHub Actions
на AMD EPYC 7763 (4 vCPU,
AVX2/FMA), Docker 29.6.1 и Compose 2.38.2. Финальный полный Requests обработан за 1330 s
при 4 CPU и analyze timeout 1800 s: 119 analyzed / 13 unsupported / 0 error,
612 находок, как в ARM64 reference. Это benchmark выбранного дерева, без ground
truth секретов; не SLA произвольного репозитория. Наблюдаемые пики по cgroup sampling:
Analyzer/Scanner — 0,98/0,11 GiB.
NumPy 2.4 поднял стандартный x86 baseline до
[x86-64-v2](https://numpy.org/doc/stable/release/2.4.0-notes.html#modulate-dispatched-x86-cpu-features);
baseline фактического wheel и PyTorch capability дополнительно снимаются в runtime.
Для старого CPU или VM со скрытыми CPU flags требуется проверка целевого узла.
На Apple Silicon эмуляция пригодна для вспомогательной отладки; приёмка проходит
на нативном AMD64. Launcher проверяет архитектуру Docker **server**, включая
случай удалённого daemon, и возвращает `daemon_platform_mismatch` при несовпадении.

Испытан rootful Docker с non-root оператором UID/GID 1001. Rootless Docker,
`userns-remap`, SELinux и корпоративные ACL/PKI этим стендом не подтверждены.
Учетная запись оператора/агента должна читать установленный launcher/deployment,
клон и доверенные configs/baselines, а также владеть приватными outputs.
При передаче пакета другой учётной записи администратор назначает владельцев/ACL;
права build-каталога 0700 не открываются автоматически. Код и установка находятся
вне очищаемого Jenkins workspace; отчёты сохраняют 0700/0600.

## Сборка

Следуйте [общему порядку сборки](advanced-build.md), выбирая на подготовке Analyzer
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
[руководства пользователя](explicit-launcher.md), передавая deployment **этого
пакета** через `--deployment-lock`. Нельзя переименовать ARM64 lock или заменить
только один image на AMD64. Импорт не означает подтверждения совместимости;
после него обязательны `verify` и контрольный scan.

Изменяется runtime/profile fingerprint, поэтому перед переходом к diff на AMD64
нужен новый полный чистый snapshot. Старый ARM64 baseline не следует переносить
как совместимый. JSON/HTML сохраняют полные значения; console содержит сводку.

Для Jenkins используйте [руководство интеграции](jenkins-explicit.md) и доверенный AMD64
пример с `SCANNER_DEPLOYMENT_LOCK`. Код примера берётся из установки scanner,
а входной Git-клон, configs и baselines располагаются вне очищаемого workspace.
Доступ к Docker и отчётам предоставляет администратор. Боевой Jenkins текущими
проверками не изменяется.

По [решению владельца о certifi](../../verification/linux-amd64/certifi-advisory.md)
версии сохранены и в v0.2.0; эксплуатация ограничена штатным offline
Docker-маршрутом с внутренним HTTP Scanner → Analyzer. Произвольный HTTPS endpoint
raw Python CLI не входит в принятую конфигурацию: перед его использованием нужна
отдельная оценка CA policy и зависимостей. Это эксплуатационное ограничение;
дополнительный программный запрет HTTPS не вводился.

## Приёмка кандидата

Непубликующий `check-cpu-platforms.yml` выполняет нативные проверки обеих
архитектур. Сравниваются решения распознавания и покрытие; абсолютная погрешность
confidence до `1e-5` допускается только при совпадении категории/значения/spans/
источника и набора находок. Порог зафиксирован до получения AMD64 результатов.
Наблюдаемое расхождение решения не скрывается этой погрешностью.

В workflow разрешены только безопасные протоколы. Полные реальные отчёты Requests,
build cache, контейнерные images и credentials не публикуются как CI artifacts.
Выпуск v0.2.0 выполнен по отдельному согласованному [плану #36](https://github.com/vovkins/ru-llm-scanner/issues/36).
Будущие слияния и публикации требуют своего поручения владельца.

## Ресурсы для пилота

Измерено на 4 vCPU и примерно 16 GiB host RAM. Первый/повторный синтетический
snapshot после импорта — 8.01/7.99 s; контейнеры каждый раз новые, OS page cache
не сбрасывался. Это запуск процесса с моделью, не физический cold boot сервера.

Для начального пилота сохраните RAM limits Analyzer `3g` / Scanner `1g`.
Для полного Requests проверены Analyzer 4 CPU и analyze timeout 1800 s;
малые проверки проходили с default 2 CPU. Контейнерные пики выбранного корпуса
не доказывают минимальную RAM хоста. Добавьте запас для ОС/Java/controller;
двум параллельным jobs нужны суммарные бюджеты двух пар контейнеров.

AMD64 image sizes по Docker — около 1,34 GiB Analyzer и 0,11 GiB Scanner,
transfer tar — 1,41 GiB, cache подготовки — 1,00 GiB. Это логические размеры,
не peak физического image store: compressed layers, unpacked snapshots, rollback,
contexts и временные файлы требуют дополнительного места. Для первого пилота
планируйте 20 GiB свободного tool-space, отдельно от клона и retention отчётов;
это стартовый запас, не доказанный минимум. Полные JSON/HTML Requests заняли
около 69 MiB. [Протоколы и область измерений](../../verification/linux-amd64/README.md).
