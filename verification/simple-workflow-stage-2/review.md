# Ревью реализации этапа 2

Scope: изменения после specification2ec86e1, до финальных docs/evidence commits.
Это focused review оболочки, а не повторная оценка качества детекторов или аудит
новых версий native dependencies. Согласованные риски сохранены.

| Область | Проверка и результат |
| --- | --- |
| Граница данных | Входной клон не определяет executable/Makefile/.env/sitecustomize; host entry работает с `-I -S`, импортируется доверенный dispatcher. Git reader и его sanitization не менялись. |
| Параметры | Make использует raw `$(value)` обычных command-line `NAME=value`, unexport неизвестных присвоений и постоянный recipe; пути/кавычки/metacharacters передаются environment→argv, без eval. Операторский Make invocation остаётся доверенным; `:=`/`!=`/`--eval` описаны в контракте отдельно. |
| Совместимость | Новый scan переводится в snapshot. Прямой CLI0/1/2, Make errors, explicit analysis/config/baseline/resources и прежний JSON launcher разделены; stderr не эхо найденных значений или bad arguments. |
| Выбор комплекта | Docker server ID/platform и точные material hashes определяют current. Проверяются bounded private JSON, ready/deployment/runtime asset hashes, native architecture и реальные image identities. Нет mtime/legacy ARM fallback. |
| Публикация current | Build lock сериализует один daemon. Verify и synthetic smoke выполняются до publish; ready/current пишутся через temporary file + atomic replace. Отказы/отмена не удаляют прошлые комплекты. Scan удерживает выбранный build directory/immutable image IDs. |
| Изоляция | Переиспользован существующий run_scan/cleanup: internal network, non-root UID/GID, read-only input/rootfs, no logs, no pull, exact random project cleanup. Infrastructure code2 имеет приоритет над ранним clean report. |
| Отчёты | Default output вне клона, UTC+random uniqueness,0700/0600; explicit output проходит прежнюю проверку. Счётчики читаются bounded JSON; для большого/неполного файла предлагается приватный JSON без неограниченного чтения. |
| Состав сборки | Exact pinned proxy source, curated source/contexts, hash artifact cache и единственный wheel текущей package version. Никаких копий всего neighbor checkout/.env/.git. Build context и инвентарь исключают generated egg-info/pycache. |
| Отмена | Реальный SIGTERM build-child проверяет process-group stop/reap; native public scan проверяет SIGTERM/cleanup и timeout. Другие wrapper faults проверены boundary тестами; полная fault matrix нового suite остаётся этапом3. |
| Публикации | Новый CI job contents:read; only safe receipt artifacts. Release/registry jobs skipped. PR #41/#42 не слиты. |

В ходе ревью исправлено включение локального `*.egg-info` в material inventory и
wheel-source. Исправлено восстановление malformed **private regular** current
после новой verified сборки; unsafe symlinks/owners не перезаписываются. Добавлены
понятные host prerequisite messages и безопасный путь private build diagnostics.

Полное восстановление повреждённого cached Python environment/test assets,
повседневный `make test`, все parallel/fault комбинации и свежий Jenkins pilot
остаются явно запланированными следующими этапами. Их готовность здесь не заявлена.

Усиленный native gate обнаружил ограничение точности диагностики раннего timeout:
launcher сохраняет code2, но secondary scanner/report failure может заменить
`run_timeout`. Core не изменён. Испытание теперь требует наблюдаемого SIGINT,
code2, известного fail-closed diagnostic и cleanup; конкретный код включён в receipt.
