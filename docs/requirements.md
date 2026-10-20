# Требования и прослеживаемость

Основание: [общая задача #1](https://github.com/vovkins/ru-llm-scanner/issues/1),
согласование этапа 1 — [#2](https://github.com/vovkins/ru-llm-scanner/issues/2),
механизм анализа — [#3](https://github.com/vovkins/ru-llm-scanner/issues/3).
Таблица задаёт сквозную приёмку; отдельные проверенные возможности перечислены
в результатах [этапа 2](../verification/stage-2/README.md) и
[этапа 3](../verification/stage-3/README.md) и
[этапа 4](../verification/stage-4/README.md) и
[этапа 5](../verification/stage-5/README.md) и
[этапа 6](../verification/stage-6/README.md). Scan API, CLI/отчёты/baseline,
штатная упаковка и Jenkins example реализованы; настоящий Jenkins/GPU не проверены.
Итоговая сквозная приёмка и согласованное историческое обновление/откат —
[этап 7](../verification/stage-7/README.md). Статусы ниже относятся к указанной
проверенной среде, не к отсутствующему release или другой инфраструктуре.

| ID | Договорённость | Спецификация | Приёмочный сценарий / этап |
| --- | --- | --- | --- |
| R01 | Локальная папка и конкретные коммиты | [Режимы](reference/scan-modes.md) | Полный снимок, refs→SHA, отсутствие checkout; 3 |
| R02 | Diff конечных состояний, полные файлы | [Режимы](reference/scan-modes.md) | Контекст вне добавленной строки, многострочный ключ; 3–4 |
| R03 | История не входит в v1 | [Режимы](reference/scan-modes.md) | Добавленный и удалённый секрет между A/B; 7 |
| R04 | Полный набор чувствительных данных прокси | [Upstream](reference/detection.md) | Каталог, одинаковые входы, словарь и отдельный корпус кода; 2, 4 |
| R05 | Перенос новых возможностей без переписывания | [Архитектура](architecture.md) | Закрепление, патч/API, обновление и откат; 2, 7 |
| R06 | CLI, Docker и будущий Jenkins | [Настройки](reference/configuration.md) | Команды/exit code, mount, артефакты pipeline; 4–6 |
| R07 | Полностью локальный анализ без интернета | [Архитектура](architecture.md) | Нет внешних соединений/скачиваний при запуске; 6 |
| R08 | Окружение сборки как у прокси, CPU/GPU | [Архитектура](architecture.md) | CA/proxy/источники зависимостей, профили, перенос образов; 2, 6 |
| R09 | HTML и JSON, полные значения/контекст | [Отчёты](reference/reports.md) | Все места, фильтры, schema, визуальная QA; 5 |
| R10 | Категория, файл, строки, коммит, source, score | [Отчёты](reference/reports.md) | Unicode/CRLF, многострочность, проверка источника; 2, 4–5 |
| R11 | Надёжный переход от проверенного A к B | [Baseline](reference/baseline.md) | Цепочка A→B→C, дерево/профиль и несовместимость; 5 |
| R12 | Ошибка не превращается в чистый результат | [Отчёты](reference/reports.md) | Нет объекта, timeout/сбой, лимит/декодирование, код 2; 3–7 |
| R13 | Границы форматов и явный охват | [Режимы](reference/scan-modes.md) | PDF/LFS/подмодуль/ссылка и явные exclude; 3–5 |
| R14 | Недоверенный репозиторий не исполняется | [SECURITY](../SECURITY.md) | Хуки/фильтры, внешние ссылки, HTML-вставка; 3, 5–6 |
| R15 | Отдельные согласования и чекбоксы этапов | [AGENTS](../AGENTS.md) | Задача/показ плана/явное согласование до каждого этапа; все |
| R16 | Качественная документация публичного проекта | [Карта](README.md), [разработка](development.md) | Правдивый статус, ссылки, примеры и актуализация; все |

## Фактический результат приёмки R01–R16

| Требования | Подтверждение | Практическая граница |
| --- | --- | --- |
| R01, R02 | Production snapshot/diff, full-file context, multiline, rename/delete/mode/type, merge и A=B в этапе 7 | Состояние Git-коммита; working/staged/untracked не сканируются |
| R03 | Clean A/B и находка промежуточного snapshot в отдельном history-сценарии | Diff не аудирует историю и не подтверждает каждый промежуточный commit |
| R04 | 77/77 raw/patched NER parity + 4 dictionary cases; 46/46 code-v1 direct parity на обеих реальных версиях | Независимое качество: TP 33 / FP 13 / FN 4, без гарантии полноты |
| R05 | Реальные v0.4.0 → da4f50a → v0.4.0, один scanner wheel, отдельные seals/profiles и восемь production шагов | Репетиция историческая, новая upstream-ревизия отсутствовала; кандидат не принят автоматически |
| R06, R07 | Штатный internal-network launcher, read-only host clone, private output/0/1/2; локальный Jenkins adapter | Настоящий Jenkins не проверен, job/RBAC/retention настраивает владелец |
| R08 | Pinned CPU ARM64 build/prepare/seal, secret mounts для CA/pip/apt и save/load с проверкой IDs | GPU/AMD64/корпоративный PKI/другой физический offline host не проверены |
| R09, R10 | Реальные JSON/HTML, Unicode/CRLF/raw collisions/кодировки/контекст и runtime schema/semantic validation | Визуальная QA этапа 5; file:// блокировался политикой встроенного браузера |
| R11 | A→B→C, profile mismatch, неправильный A, old/new baseline rejection при upgrade/rollback | Baseline доверенный по происхождению; JSON/SHA-256 не цифровая подпись |
| R12, R13 | Production errors/timeouts/crash/OOM/signals; unsupported/exclude/limits отражены явно | Ранний отказ может не оставить отчёта, CPU join не жёсткий deadline, JSON/HTML атомарны отдельно |
| R14 | Hostile config/hooks/filters/textconv/includes/replace/grafts/promisor/links и неизменные input fingerprints | Host/daemon доверенные, object store не должен меняться параллельно снаружи |
| R15 | Отдельные задачи этапов, явные согласования реализации и слияния в чате | v0.1.0 и публичные GHCR images отдельно разрешены в #31; инфраструктура Jenkins не настраивается |
| R16 | Обновлённые guides/examples/status, contracts/ссылки/format и safe evidence | MIT выбран владельцем; приватный vulnerability contact пока не объявлен |

## Состояние проекта

Этапы 1–7 реализованы и проверены в заявленных границах. После отдельного
согласования пользователя 2026-10-19 семь PR #4 → #6 → #8 → #10 → #12 → #14 → #15
последовательно слиты в `main` с сохранением исходных коммитов.
[Результаты интеграции и повторных проверок](../verification/main-integration/README.md)
отделены от исторических свидетельств [этапа 7](../verification/stage-7/README.md).
Затем завершён цикл подготовки к эксплуатации #16 и слиты семь PR исправлений/
документации: [интеграция](../verification/operations-main-integration/README.md).
Для первого выпуска `0.1.0` владелец 2026-10-20 выбрал MIT и публичные GHCR images
и разрешил публикацию после финальных проверок: [#31](https://github.com/vovkins/ru-llm-scanner/issues/31),
[release evidence](../verification/release-v0.1.0/README.md), [лицензирование](licensing.md).
Закрытый канал сообщения об уязвимостях пока не объявлен; фактическая процедура
описана в [SECURITY](../SECURITY.md). Эти решения не выдаются за выполненные.
