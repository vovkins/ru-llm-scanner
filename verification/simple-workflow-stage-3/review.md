# Focused review этапа 3

Основание: согласованный #43. Scope — изменения после8dfa134, draft PR #44,
зависимости #41/#42 остаются без слияния. Это review test orchestration и материалов;
новая оценка качества детекторов/зависимостей сюда не относится.

| Область | Проверка |
| --- | --- |
| Публичный интерфейс | Сохранены build/scan/diff/test/help. Test не принимает произвольный input/config/deployment; выбирает текущий проверенный комплект. Missing/stale resources не запускают acquisition и дают2/следующее действие. |
| Обязательные группы | Полное unittest discovery; skipped/empty discovery/отсутствующие критические CLI/dictionary/config/Git/pipeline/report/upstream/workflow модули не становятся pass. Ожидаемый scanner1/2 в synthetic case отделён от итогового suite0/2. |
| Python-инструменты | Собственный venv с прежними pinned tools/dependencies. Inventory проверяет содержимое файлов tools/environment и стандартные venv links; генерируемые pycache/pyc исключены. Изменение учитываемых файлов требует explicit build. Автоматического install в test нет, pip version/index запросы отключены. |
| Восстановление | Build создаёт новый private venv, проверяет versions/pip check/inventory и атомарно меняет pointer. Не chmod/удаляет старый или чужой каталог. Support metadata продвигается после проверки; исправные runtime images переиспользуются. |
| Unit fixture | Existing prepare_unit_assets переиспользован с exact historical source/constraints/patches. Source-only старый ARM64 fixture не подменяет текущую модель или runtime lock. Глобальный `.build/analyzer` не перезаписывается; suite копирует проверенные материалы в собственный run-dir. |
| Параллельность | Каждый test-run получает UUID/private directory/свою копию assets. Builds сериализованы прежним flock. Два runtime scan используют отдельные Compose projects/outputs. |
| Lifecycle | Дочерние процессы контролируются по собственным PIDs/process groups. Private Docker wrapper записывает только созданные этим запуском random project IDs; finally cleanup использует эти IDs, а не общий prefix/чужие контейнеры. Ошибка cleanup меняет итог на2. |
| Вывод | Logs и JSON/HTML остаются private; console содержит группы, итог, время и diagnostic path. Safe summary содержит числа/статусы/идентификаторы тестов без значений/body/env/raw traces. Runtime canary проверяется в private report и не должен попадать в console. |
| Совместимость | Core src, detection/model/dictionary/dependencies/default locks и legacy launcher не менялись. Прямой scan/diff0/1/2 и strict baseline переиспользованы. Полная прежняя native release/Requests/quality/Jenkins матрица сохранена отдельно. |
| CI/publication | Новый manual mode в существующем workflow, native jobs contents:read. Release/registry jobs skipped. Только safe receipt загружается; образы/отчёты/модели/сырые logs не публикуются. |

Первый native run выполнил build на обеих CPU, но не прошёл unit. Исправлены
test-only зависимости от human-readable Entering/Leaving сообщений recursive
GNU Make и действующего Docker context/API хоста. Проверка literal argv/marker
side effects сохранена; unavailable daemon моделируется own executable.
Отказ не замаскирован пропуском группы или изменением expected suite success.
Локальный новый venv+isolated fixture после исправлений прошёл225/0skip.

Ограничения: тестовые repos синтетические; full Requests/independent quality,
реальный новый Jenkins/migration и пользовательский clean documentation walkthrough
выполняются отдельными этапами. SIGKILL/host loss не объявляются новым проверенным
сценарием этого suite. Принятые certifi/native риски не исправлялись.
