# Ревью controlled update

База —d39c8e6 (#45). Изменения ограничены stdlib maintainer compare/prepare,
общим verified source-preparation seam, schema/review/adapter fixture, tests/docs
и отдельным read-only CI mode. Пользовательские четыре команды не расширены.

## Проверенные границы

- Источники читаются как Git objects полных SHA через существующий изолированный GitRepository. Рабочий Python/config/hooks/filters не импортируется и не исполняется; scanner Git reader не изменён. Nonregular entries/external metadata/alternates/symlink paths отвергаются.
- Сравнивается всё дерево: явные before/after mode/OID/SHA-256, изменения вне прежних97 source paths, однозначный exact-content rename или честные delete/add. Каждый changed path обязан присутствовать в review; решение decision блокирует готовность.
- Review строго связан с A/B и hashes каждого изменения, unknown keys/duplicate JSON/types/stale inventories отвергаются. Новые model/dependencies/build/notices изменения выделяются как blockers, даже при export disposition. Нет автоматического main/latest или dependency upgrade.
- Импорты и tracked literal resources проверяются после patches. Отсутствующий выбранный локальный dependency блокирует source readiness. Dynamic imports/вычисляемые пути/внешние imports и API поведение требуют runtime tests; acknowledgement не является доказательством совместимости.
- Новая BASE64_POLICY содержит цифры: прежняя source-lock regex их запрещала. Validator теперь допускает цифры в PRESIDIO именах; остальная текущая среда/locks прежние. Synthetic regression проверяет полное имя, не обрезанный BASE.
- Патчи проверяются по checksum, последовательным before/after hashes и точным hunks. Конфликт оставляет blocked/ошибку без ready marker. Нет fuzz/авторебейза. Review replacement хранится отдельно, прежние четыре patch files не изменены.
- Candidate API patch переносит пять групп scanner metadata на точный9e47e65. Использует четыре публичные SOURCE_* константы вместо приватного _KNOWN_SOURCES. Статический native gate сверяет тот же полный набор contextual_contract/native_credential/ner/structural; реальный API parity остаётся этапом6.
- Общий prepare_payloads перепроверяет точное множество/hash/model/constraints до создания context и использует прежнюю генерацию/verify_context. Explicit prepare тоже делегирует ему. Current upstream/dictionary/model/requirements/default deployments не переключаются.
- Output только новый, private0700; CLI files0600, вне source/current workflow. No chmod/chown существующего пути, перезаписи готового результата или чистки чужих каталогов. Candidate marker пишется последним, включает все content hashes/profiles и два false флага принятия/runtime acceptance.
- Source comparison не вызывает Docker/pip/curl/wget/fetch. Native outer явно получает нужные SHA до проверки, отключает auto-maintenance тестового Git clone и затем требует точную неизменность всех файлов. Первоначальный отказ сохранён, inventory gate не ослаблен.
- Native current-engine regression использует прежний da4f50a. Candidate logistic не участвует в model runs данного этапа. Новые runtime/model/quality/Requests/Jenkins/rollback не выдаются за выполненные.
- Workflow имеет contents:read и только safe receipt artifact; release jobs исключают upstream_update. Публикаций, merge и изменения prod/соседнего proxy нет.

## Meaningful regressions

19 tests проверяют новый module/resource/test/setting и полноту source export,
неявно потерянный импорт/resource, explicit exclusion, repeat content equality,
schema/ложное adoption claim, deletion/rename, foundation blocker, exact patch
conflict/replacement/tampering, stale lock/review/duplicate JSON/types, dirty working
files/hooks/shell-like SHA, nonregular Git entries/alternates/external gitdir,
unsafe output/review symlink, payload corruption и настоящий isolated CLI/private
files/both profiles. Вся unit discovery244 теста, без skips/missing groups.

Эти проверки не подтверждают качество новой модели. Реальная functional acceptance
нового Base64 code и предлагаемый logistic default требуют следующего отдельно
согласованного этапа6 (#49). Принятые ранее certifi/native риски не исправлялись.
