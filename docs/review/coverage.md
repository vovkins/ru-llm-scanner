# Область ревью, границы доверия и матрица проверок

Ревизия: `336feb64b201b0e9b807059f3d60b50fdee41ebb`.
Начальная инвентаризация: 180 tracked files, 67 Python files, 131 unit methods.
Ревью проводилось без делегирования. Это статическое исследование с точечными
воспроизведениями; line coverage и независимый внешний security audit не измерялись.
Полный перечень Python-файлов и их хешей — в [инвентаризации](scope.json).

## Маршруты и доверие

1. Администратор выбирает доверенные source/runtime locks и build profile,
   экспортирует allowlisted Git bytes upstream, готовит зависимости/модель,
   выполняет build/seal, собирает scanner с engine bundle, проверяет и переносит
   готовый комплект. Online prepare имеет отдельные источники/credentials;
   `--network none` runtime не заменяет контроль build/daemon.
2. Пользователь получает scanner checkout/launcher, deployment lock и образы,
   заранее подготовленный self-contained Git clone, отдельный output и при
   необходимости доверенные config/baseline. Launcher проверяет IDs/пути,
   создаёт уникальный Compose project и владеет только его cleanup.
3. Container CLI формирует конфигурацию и engine → проверяет readiness →
   Git thread фиксирует refs и читает объекты через отдельный metadata-view →
   text-v1 определяет scope/кодировку → очередь передаёт полные тексты Analyzer
   и словарю → findings фиксирует координаты → reports/validation/writer
   публикуют JSON и HTML → exit code задаёт итог запуска.
4. CI adapter выбирает репозиторий/config/baseline из доверенных roots и
   передаёт argv launcher без shell interpolation. Jenkins controller и
   политика доступа/retention находятся за пределами проверенного стенда.

Недоверенные: Git config/refs/tree/blob/paths, содержимое файлов и HTML-подобные
строки. Доверенные: host/daemon, executable path Git/Python/Docker, launcher,
lock/config/словарная policy из проверенного комплекта и происхождение baseline.
Object store не должен меняться хостовым процессом во время scan. Проверка
схемы/SHA-256 не заменяет аутентичность источника. Полные sensitive values
разрешены только в приватных выходных отчётах, не в console/evidence.

## Карта исследованного кода

| Область | Файлы | Глубина / итог |
| --- | --- | --- |
| Entry points/config | __init__, __main__, cli.py, configuration.py | Подробное чтение parser, preflight/errors/cancellation и нормализации профиля; stdout ограничен сводкой |
| Git | git_repository.py, git_plan.py | Подробное чтение изоляции/metadata/ref/OID/subprocess/tree и A/B selection; неподдержанные layout дают ошибку |
| Text | text_policy.py | Подробное чтение glob/encoding/BOM/magic/NUL/LFS/limits; неподдерживаемость отражается явно |
| Analyzer/dictionary | analyzer.py, dictionary.py, engine.py | Подробное чтение HTTP/capabilities/signature/offset/response limit и pinned policy; нет env proxy/follow redirects в клиенте |
| Pipeline/findings | pipeline.py, findings.py | Подробное чтение queue/workers/CPU join/errors/baseline inheritance/ordering/context; память всего результата не ограничена |
| Отчёты | reports.py, report_validation.py, output.py, html_report.py; public/packaged schemas | Подробное чтение envelope/инвариантов/записи/escaping/CSP, сверка conditional schema; RV-05 — документированная разница preflight |
| Upstream/build | artifacts.py, upstream.py; scripts/analyzer.py, build_scanner.py, prepare_scan_engine.py | Проверены allowlists, exact patch, hashes, constraints, seal, secret mounts и install assets; источник upstream доверенный, не произвольный scanned clone |
| Docker runtime/transfer | scripts/docker_scanner.py, docker/scanner.Dockerfile | Подробное чтение ID/mount/resource/timeout/ownership/error/export/import; RV-02 |
| Jenkins | examples/jenkins/run_scan.py, Jenkinsfile | Подробное чтение trusted roots, argv, result/status/signal/archive; RV-01 |
| Dev image/inventory | docker/*test.Dockerfile, probe_runtime.py, license_inventory.py; capture_licenses.py | Сверка зависимостей, mounted inputs, versions/model/notices; RV-03, свежий CVE scan не выполнялся |
| Dev integration | check_analyzer/scan/cli_integration.py, check_upstream_tests.py | Проверены границы mounts, image identity, источники доказательств и subprocess; RV-04 и устаревший dev image |
| Acceptance/faults | check_docker_integration.py, check_deployment_extras.py, check_runtime_faults.py, check_acceptance.py | Исследованы ownership, synthetic fixtures, assertions, cleanup и соотношение report/process code; новый полный Docker-прогон отложен до исправлений |
| Rehearsal | prepare_rehearsal.py, build_rehearsal_scanner.py, check_rehearsal_parity.py, check_upgrade_rollback.py | Проверены отдельные contexts/locks, exact anchors и настоящий baseline transition; старый прогон не объявляется повторённым |
| Test tooling | check_cli_tests.py, check_git_layer.py, check_contracts.py; tests/*.py и helpers; tests/integration/*.py, corpus loader | AST/каталог всех test methods, чтение существенных assertions/fixtures/критических путей, выборочный запуск 13 tests; различаются stub, model parity и independent metrics |
| Документация | README, docs map/requirements/ADR/quickstarts/build/operations/security/licensing/development/Jenkins | Сверка ролей, последовательности, defaults/предусловий и заявлений о готовности; DOC-01/DOC-02/TEST-01 |

Таблица описывает глубину по областям. Она не утверждает проверку каждой ветви
каждого dev-теста или полный security review экспортированных 97 upstream files.
Собственный runtime исследован подробно; upstream изучен на границе интеграции,
закрепления и применимых API/артефактов. Статические выводы и новые запуски разделены.

## Матрица рисков и существующих доказательств

| Риск / контракт | Существующие тесты и свидетельства | Пробел / дальнейшая проверка |
| --- | --- | --- |
| Подмена состояния рабочей папкой | test_git_repository snapshot/raw paths/read-only/fingerprint, production acceptance | Сохранить проверки неизменности входа после исправлений |
| Исполнение hooks/config/filters/fetch | test_git_security; hostile acceptance этапа 7 | Повтор production hostile в этапе 4; arbitrary host mutation вне trust model |
| Некорректный/повреждённый object или tree | missing/type/hash/tree limits tests, promisor/fifo metadata cases | Loader deployment JSON не использует эти guard rails: RV-02 |
| Неполный diff/rename/merge/history | test_git_plan, baseline mode/type/SHA256, acceptance graph | История между A/B намеренно не сканируется |
| Неверное декодирование/скрытый пропуск | test_text_policy BOM/legacy/NUL/LFS/magic/limits/conflict; partial pipeline | Сохранить код 2 для decoding/limits и явные unsupported/excluded |
| Ошибка модели/профиля/HTTP | test_analyzer malformed response/signature/health/deadline/size/concurrency; stage 2 parity | Реальные NER/upstream tests повторять по затронутым слоям; no retry inference |
| Потеря словаря / drift upstream | pinned dictionary tests, hashes, stage 7 historical source/parity | Assets обязательны для asset-required тестов; не маскировать skipped |
| Ошибочное наследование clean | test_baseline chain/profile/tree/report/required; upgrade/rollback | Точность signed provenance не заявляется; после изменения анализа новый snapshot |
| Ошибки координат/потеря контекста | test_findings, test_reports, независимые scan_offline coordinates | Новый probe: 4200 позиций CR/LF/emoji прошли; будущий regressions не должен использовать тот же oracle |
| Ложный clean после сбоя/отмены | pipeline/CLI/report partial/cancel/final-health tests; production OOM/signals | RV-01 лежит на следующей границе adapter и отсутствовал в штатных сценариях |
| Расхождение JSON/HTML после FS failure | test_output repair/atomic create/symlink/concurrent writer | Сохраняется per-file atomicity, process exit 2 обязателен; RV-05 — отдельная политика папки |
| XSS/внешние HTML resources | test_reports HTMLParser/CSP hashes, визуальная QA этапа 5 | Browser QA этапа 4 после изменения renderer/docs demo, URL policy не обходить |
| Контейнеры/egress/чужой cleanup | production inspect/no route/UID/RO/caps/logs; ownership labels; parallel cases | RV-04 в legacy dev tooling; SIGKILL/daemon loss требует operator cleanup |
| Offline build/package/IDs | prepare/context/inventory/build/seal; extras negative checks/save-load | Другой физический host/store и новая online closure не доказаны; DOC-01 |
| Успех CI при некорректной сводке | Jenkins tests команд/paths; extras штатные 0/1/2 | RV-01: добавить реальный adapter subprocess с empty/malformed/wrong-type/inconsistent stdout |
| Воспроизведение dev scan | frozen code-v1, old stage 4/5/6/7 evidence | RV-03: текущий Dockerfile сломан; старое evidence не подтверждает текущий рецепт |
| Ёмкость RAM/диска/времени | queue bounds/CPU join и kernel OOM подтверждены ранее | Этап 4: измерить representative small/medium/large synthetic workload; budget не равно capacity |
| Известные уязвимости/лицензии | pinned constraints и license inventory | Этап 4: свежая база/дата/источники; license/contact требуют решения владельца |

## Положительные результаты статического ревью

Git reader создаёт отдельный metadata-view, не применяет config проверяемого
клона, ограничивает subprocess и проверяет OID. Raw paths не используются для
чтения файлов рабочего дерева. Классификация scope отделена от успешного анализа.
Baseline требует clean/complete, совместимый профиль и точное дерево A;
изменённые файлы анализируются полностью. Оба обязательных слоя обнаружения
должны завершиться до принятия файла как analyzed. Последний health check может
инвалидировать запуск, сохранив завершённые findings.

Штатный Docker launcher использует immutable references, internal network,
read-only вход/root FS, non-root, disabled logs и cleanup точного UUID project.
HTML строит данные как escaped text с фиксированными CSP hashes; JS группирует
DOM nodes и использует textContent. Writer резервирует каталог и создаёт файлы
без замены чужого racing файла. Эти свойства подтверждены чтением соответствующего
кода и прежними тестами; здесь не заявлен новый полный production-прогон.

## План дальнейшей валидации

Этап 2: regression cases RV-01/RV-02, восстановленный dev image + schema/import
smoke, проверка curated argv/cleanup, выбранная политика RV-05. Запуск затронутых
unit/integration групп, затем полный актуальный unit без skipped на подготовленных
assets. Детекторы/модель/профиль остаются прежними, если не выявлено и отдельно
не согласовано изменение семантики.

Этап 3: README и docs/user/admin/reference с двумя маршрутами доставки:
готовый пакет и fresh build с собственными locks. Передача пользователю должна
перечислять launcher, доверенный deployment lock, импортированные images,
подготовленный clone, config/baseline при необходимости и private output root.

Этап 4: полный применимый Git/contract/runtime/model/production набор, faults,
independent code-v1, real HTML, новый clean documentation walkthrough и capacity
measurements; актуальная проверка dependency advisories отдельно от offline scan.
Повтор upgrade/rollback обосновывается изменениями build/locks/интеграции.
Недоступный Jenkins/Linux/AMD64/GPU/PKI/другой offline host отмечать явно;
не превращать отсутствие стенда в успешную проверку.
