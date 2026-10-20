# Уточнение native-рисков — 2026-10-20

Речь о двух images кандидата ru-llm-scanner PR #29: scanner (Python CLI/Git/JSON/HTML)
и Analyzer (локальные NER/PyTorch/spaCy). Это зависимости самого сканера, а не
библиотеки проверяемого проекта. Текущий deployment ru-llm-proxy отдельно этим
разбором не аттестован. Общие исходники Analyzer не означают одинаковые native versions.

## Использование

| Библиотека | Измеренная версия | Роль |
| --- | --- | --- |
| libstdc++ | gcc-14 14.2.0-19, libstdc++.so.6.0.33 | C++ runtime для native ML components Analyzer. Загружен после импорта torch/spaCy/NumPy/tokenizers. В scanner пакет установлен, но в контрольном импорте core не загружен; Git прямо от него не зависит |
| glibc | 2.41-12+deb13u4 | Базовый C runtime обоих контейнеров: Python/Git/native modules, память, строки, системные взаимодействия |
| zlib | 1.3.1, Debian 1:1.3.dfsg+really1.3.1-1+b1 | Git читает сжатые objects/packs; Python также загружает zlib. Git непосредственно импортирует inflate/deflate/crc32 |

[Evidence](native-reachability.json) содержит IDs точных images, hashes ELF, наблюдаемые
loaded libraries и выбранные dynamic imports. Контейнеры были read-only/network-none,
без ввода репозитория и без inference/эксплуатации. Наличие загруженной библиотеки
не доказывает вызов конкретной уязвимой функции; отсутствие dynamic symbol не
исключает все indirect/static paths.

## Пять совпадений

1. **CVE-2026-102010, PBDS binary heap erase_if.** Ошибка оставляет указатель на уже
   освобождённый буфер; возможны падение и повреждение памяти. Вход репозитория
   должен привести native потребителя к этой конкретной структуре и операции.
   Такой маршрут в scanner не установлен. [Upstream fix](https://github.com/gcc-mirror/gcc/commit/aaa8351f4d2e636f9680a1f0a8ebc2f0a60611e6)
   находится в template header `ext/pb_ds/.../erase_fn_imps.hpp`: важно проверить
   использование и происхождение сборки wheels, а не только обновить shared runtime.

2. **CVE-2026-95619, aligned operator new overflow.** При определённых allocator
   implementations округление огромного размера может переполниться и выделить
   меньший буфер. [Upstream](https://github.com/gcc-mirror/gcc/commit/200183d4ab5d57575f3dfebc6af3baf649910b9e)
   явно исключает `posix_memalign` path. В точном системном ELF ARM64 function
   `_ZnwmSt11align_val_t` вызывает `posix_memalign@plt`. Поэтому finding признан
   **неприменимым к этой системной сборке**, без package upgrade/принятия риска.
   Это не аттестация каждого статически слинкованного native компонента wheels.

3. **CVE-2026-19542, glibc tdelete.** Выход указателя за стековый буфер при удалении
   из дерева определённой глубины. Нужны операции `tsearch/tdelete` с деревом порядка
   миллиона узлов; просто большое число файлов не означает вызов этих API.
   Управляемый репозиторием маршрут в такие деревья не найден; полного call graph нет.
   [Debian/source description](https://security-tracker.debian.org/tracker/CVE-2026-19542).

4. **CVE-2026-27171, zlib CRC combine.** Определённые CRC combine API при отрицательной
   длине могут уйти в бесконечный цикл и потреблять CPU.
   [Исправление upstream](https://github.com/madler/zlib/commit/ba829a458576d1ff0f26fc7230c6de816d1f6a77)
   проверяет `len2 < 0`. Обычный `crc32`/inflate не равен `crc32_combine64`.
   В исследованном Git ELF прямых imports combine нет; Python scanner их напрямую
   не вызывает. Доказательства маршрута из crafted Git object нет, полный native
   граф ещё не установлен. Возможное последствие при достижимости — отказ проверки/CI.

5. **CVE-2026-85091, nonblocking gzip writer.** При определённой последовательности
   blocked/retried gzwrite/gzprintf возможен выход за heap buffer.
   [Upstream fix](https://github.com/madler/zlib/commit/df84af25dc1942490e1d1c899a07619152a46148).
   Штатный Git-read путь не пишет gzip такими API; их прямых imports у Git нет.
   Дополнительно есть расхождение диапазонов: описание CVE указывает1.3.1.2–1.3.2,
   [Debian](https://security-tracker.debian.org/tracker/CVE-2026-85091) сохраняет1.3.1
   vulnerable и ссылается на обсуждение более раннего поведения. Finding не снят
   только по semver или по отсутствию имени одной функции.

Для 1/3/4/5 остаётся assessment без доказанного exploit path. По четырём записям
владелец 2026-10-20 [явно принял риск для закрытого контура](risk-acceptance.md).
Техническая оценка сохранена; выполнение итоговой приёмки ещё не согласовано.

## Сценарии и последствия

Входная граница — недоверенный Git-клон и извлечённый из него текст. Автор
репозитория может управлять contents/metadata, но не выбирает закреплённые
модель, wheels и image. Выполнения hooks/build/scripts этого репозитория нет.
Чтение Git objects и NER всё равно передают данные native-коду: отсутствие
запуска repository scripts само по себе не доказывает безопасность парсеров.

Если удаётся вызвать зависание/падение native component, ожидается exit2/неполнота,
а CI не продвигает clean baseline. CPU/RAM limits и общий timeout ограничивают
ресурсы, но не исправляют ошибку. Обычный дорогой NER/SVG или OOM не являются
доказательством ни одной из этих CVE.

При реально достижимом memory corruption нельзя ограничивать оценку одним DoS:
потенциально возможна компрометация процесса и искажение распознавания/отчёта.
Конкретный RCE для scanner не показан. Scanner имеет доступ к input read-only
и output RW; Analyzer получает анализируемый текст и не имеет bind mount клона.
Изоляция non-root/read-only/cap-drop/internal network/no Docker socket сокращает
доступ, но не защищает уже скомпрометированный процесс от чтения доступного текста
или фальсификации результата. Выход на Docker host этими данными не доказан.
