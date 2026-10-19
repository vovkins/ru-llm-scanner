# Чтение Git и подготовка текста

Внутренний Git API читает выбранные состояния, сравнивает деревья и готовит
полный текст поддерживаемых файлов. Он подключён к [scan pipeline](scan-api.md),
координатам и [CLI snapshot/diff](cli-quickstart.md), отчётам/baseline и
[штатному Docker launcher](user/README.md).

## Поддерживаемое окружение и layout

Нужны POSIX, Python 3.11+ и установленный Git в доверенном PATH. Проверены
macOS ARM64 / Apple Git 2.39.5 и Linux ARM64 / Git 2.47.3. Git не устанавливается
и не обновляется автоматически при работе reader. Windows-native окружение
не проверено; штатный запуск использует Linux Docker.

Поддерживаются обычный самодостаточный клон с каталогом `.git` и bare-репозиторий.
Допускается `.git`-файл, указывающий на metadata внутри явно заданного корня,
без символических ссылок в пути. Reader не ищет репозиторий в родительских
каталогах. SHA-1 и SHA-256, loose objects и packfiles проверены.

Не поддерживаются shared clones с alternates, linked worktrees с commondir,
внешний git-dir/object store, reftable и неизвестные storage extensions.
Символические ссылки и специальные файлы в используемых metadata/object store
отклоняются, в том числе ссылки внутри корня. `objects/info/alternates` и
`http-alternates` отклоняются целиком. Это ошибка layout, а не чистый результат.
Для такого входа подготовьте отдельный самодостаточный клон заранее.

Shallow/partial clone допустим, если требуемые commit/tree/blob уже доступны
локально. Полная история не нужна. Missing object даёт явную ошибку; reader
не загружает недостающее. Данные LFS и подмодулей не читаются.

## Изоляция Git

Reader создаёт приватный временный metadata-view вне проверяемого репозитория.
В него копируются проверенные HEAD, refs, packed-refs и shallow, а config
создаётся заново с bare/object-format и запретом протоколов. Git читает объекты
через `GIT_OBJECT_DIRECTORY` из предварительно проверенного локального store.
Оригинальные index, hooks, attributes, config includes, reflogs и grafts в view
не переносятся. Рабочие файлы не открываются.

Исходный config читается как ограниченный обычный файл и разбирается отдельным
`git config --file ... --no-includes` в изолированном окружении. Из него
извлекаются только версия/формат хранилища и проверяются известные extensions;
remote, helpers и остальные настройки не становятся конфигурацией reader.
Управление includes определяется [контрактом Git config](https://git-scm.com/docs/git-config#Documentation/git-config.txt---no-includes).

Все процессы запускаются массивом аргументов без shell. Наследуемые `GIT_*`,
proxy, askpass, trace и loader-переменные не передаются. Замены объектов,
lazy fetch и протоколы отключены; remote/promisor config в view отсутствует.
На старом Git дополнительная переменная `GIT_NO_LAZY_FETCH` может не работать,
поэтому безопасность не опирается только на неё. См. [переменные Git](https://git-scm.com/docs/git#_environment_variables).

Используются `rev-parse`, `config` и `cat-file --batch`. Нет checkout, diff,
textconv, clean/smudge, pager, credential helpers или выполнения содержимого
репозитория. Потоки stdout/stderr ограничены и имеют общий дедлайн; ошибки
содержат только код, без stderr, ревизии или blob целиком.

Refs фиксируются при открытии reader; после разрешения используются полные
commit OID. Объекты должны оставаться неизменными до закрытия context manager:
нельзя одновременно удалять/repack/подменять object store. Защита от активной
параллельной подмены файлов хостовым процессом не заявлена. Будущий штатный
Docker-запуск монтирует вход read-only. Проверка не изменяет сам репозиторий.

## Python API

Установка окружения описана в [development](development.md). Пример читает
объекты, не запускает Analyzer и не сохраняет отчёт с чувствительными значениями:

```python
from pathlib import Path
from ru_llm_scanner.git_repository import GitRepository
from ru_llm_scanner.git_plan import plan_snapshot, plan_diff
from ru_llm_scanner.text_policy import TextPolicy, EncodingOverride

policy = TextPolicy(
    exclude=("generated/**",),
    encoding_overrides=(EncodingOverride("legacy/**", "cp1251"),),
)
with GitRepository(Path("/repo")) as repository:
    plan = plan_snapshot(repository, "HEAD")
    # Альтернатива: plan_diff(repository, "COMMIT_A", "COMMIT_B")
    for prepared in plan.prepare(repository, policy):
        state = prepared.content.state
        if state == "ready":
            text = prepared.content.text  # Полный текст; не выводить в консоль.
        elif state == "error":
            code = prepared.content.reason  # Нельзя считать обработанным.
```

`GitSnapshot` содержит commit/tree OID, object format и отсортированные записи.
`GitEntry` хранит `path_bytes`, `mode`, `oid`, а также вычисляет `path` и
`path_bytes_b64`. `path` — UTF-8/backslashreplace: он может совпасть для двух
разных сырых имён. Идентичность/сортировка всегда основаны на байтах. Отображение
пути не используется для открытия файлов и требует экранирования в UI/консоли.

`GitPlan.files` содержит полный манифест B; `selected` означает выбор по
изменению состояния, до scope/классификации. Смена executable bit — `modified`;
смена обычного файла на ссылку/подмодуль — `type_changed`. Exact rename связывает
одинаковые mode/OID в порядке сырых путей и выбирает файл по новому пути.
Изменённое переименование может быть added+deleted. `deleted` сохраняет все
пути A, отсутствующие в B, включая старые пути exact rename.

Сравнение не требует предка/потомка, не вычисляет merge-base и не читает
промежуточную историю. Для merge используется явно заданный A. При A=B
выбранных файлов нет. [Подробная семантика](reference/scan-modes.md).

`prepare()` — итератор, удерживающий один выбранный файл за раз. Неизменённые
blobs не читаются. Caller не должен собирать все большие тексты в один список;
параллельность и дальнейшая обработка ограничены в [pipeline](scan-api.md).

| Внутреннее состояние `FileContent` | Значение |
| --- | --- |
| `ready` | Полный текст строго декодирован; детекторы ещё не запускались |
| `not_selected` | Неизменённая запись diff, blob не читался |
| `excluded` | Путь исключён явно, содержимое не читалось |
| `unsupported` | За пределами text-v1: причина сохранена |
| `error` | Обязательное чтение/декодирование не завершено |

Это не статусы JSON-отчёта. Reader не назначает `analyzed`, `inherited`,
assurance или успешный exit code сканирования. Текст исключён из repr.

## Scope, форматы и кодировки

Include/exclude используют регистр, dotfiles и `*`/`?` внутри сегмента,
отдельный сегмент `**` — ноль и более каталогов. Нет скрытых исключений
`.gitignore`, vendor/tests/lock или по расширению. Шаблоны сопоставляются с
`path`; это явная семантика v1 при не-UTF-8 именах. Недопустимые шаблоны и
неизвестные/нетекстовые codecs отклоняются при создании policy.

Сначала scope, затем mode и сигнатуры из [таблицы text-v1](reference/scan-modes.md).
Классификация смотрит до 8192 байтов; для неподдерживаемого большого объекта
stream прерывается, Python не загружает весь blob. Малый LFS pointer должен
целиком соответствовать каноническому v1, LF, version/oid/size и допустимым
упорядоченным ext-строкам. Основание: [LFS pointer specification](https://github.com/git-lfs/git-lfs/blob/main/docs/spec.md)
и [extensions](https://github.com/git-lfs/git-lfs/blob/main/docs/extensions.md).
Лимит scanner для этой классификации — 8192 байта. Ложный/обрезанный pointer
остаётся текстовым кандидатом; никакой LFS-команды не вызывается.

Размер blob известен из batch header до полного чтения. Для выбранного
текстового кандидата default 10 MiB; превышение — `file_too_large`. Большой
распознанный PDF/архив/бинарный объект остаётся unsupported с причиной.
Полностью прочитанные commit/tree/blob сверяются с собственным Git OID
(заголовок типа/размера и содержимое, SHA-1 либо SHA-256).

UTF-32 BOM проверяется раньше UTF-16; удаляется только начальный BOM.
Без BOM используется UTF-8 либо явно назначенный codec. Для UTF-16/32 без
BOM задаётся конкретный endian codec, например `utf-16-le`; неопределённый
`utf-16`/`utf-32` без BOM даёт `decode_error`. BOM обязан согласоваться с
override. Пересекающиеся правила разных codecs дают `encoding_conflict`.
NUL-байт считается бинарным признаком вне распознанного UTF-16/32; в этих
кодировках он входит в нормальное представление символов. Неверные байты,
обрезанные wide-символы и lone surrogates дают `decode_error`. Ни `replace`,
ни автоматический fallback в cp1251 не используются. CR/LF/CRLF, emoji,
combining marks, пробелы и внутренний U+FEFF сохраняются.

## Лимиты и ошибки

`GitLimits` — операционные пределы reader, не настройки качества детекторов:

| Предел по умолчанию | Значение |
| --- | --- |
| Одна Git-команда / один object stream, общий дедлайн | 30 секунд |
| Сумма копируемых refs/metadata и отдельный commit/tree | 64 MiB |
| Исходный config | 1 MiB |
| Число entries при обходе metadata и дерева | 1 000 000 |
| Глубина дерева Git | 256 |
| Буфер диагностики отдельного процесса | 64 KiB |

Превышение даёт `git_resource_limit`/`git_timeout`, не чистый пропуск.
Основные ошибки: `revision_unavailable`, `git_layout_unsupported`,
`git_config_invalid`, `git_reference_invalid`, `git_tree_invalid`,
`git_object_missing`, `git_object_corrupt`, `git_object_type_mismatch`,
`git_object_read_error`, `git_read_error`, `decode_error`, `encoding_conflict`.
Ошибка перечисления фатальна для манифеста; ошибки выбранного файла сохраняются
в его `FileContent`, последующие файлы могут готовиться. Финальная приёмка
pipeline обязана трактовать такой файл как неполную проверку.

## Проверки

```bash
.venv/bin/python scripts/check_git_layer.py --output .build/stage-3/host-tests.json
```

Независимый dev-образ содержит только Python/Git. В Docker build передаётся
минимальная папка с одним Dockerfile; корень проекта и `.git` не отправляются:

```bash
mkdir -p .build/stage-3/git-test-context
cp docker/git-test.Dockerfile .build/stage-3/git-test-context/Dockerfile
docker build --platform linux/arm64 -t ru-llm-scanner-git-tests:stage3 \
  .build/stage-3/git-test-context
.venv/bin/python scripts/check_git_layer.py \
  --docker-image ru-llm-scanner-git-tests:stage3 --platform linux/arm64 \
  --output .build/stage-3/linux-tests.json
```

Сборка может использовать сеть для Git packages; сами тесты — `--network none`,
UID 65534, без capabilities, read-only FS, tmpfs и отдельная папка результатов.
Launcher копирует только явный перечень тестовых исходников, не весь checkout.
В image не запускается NER; это не production Compose сканера.
[Результаты этапа 3](../verification/stage-3/README.md) фиксируют версии,
Image ID и хеши кода. Повторные сборки dev-образа могут получить другую версию
Git из apt; реальная версия всегда записывается в результат, без утверждения
о побайтовой воспроизводимости тестового окружения.
