# Готовность к локальному пилоту и ограничения

Матрица относится к [точному кандидату](candidate-manifest.json), а не к любой
будущей сборке. `passed` — измеренная проверка; «ожидаемый отказ» — нужный код 2;
`not-tested` — подтверждения на таком стенде нет. Предыдущие результаты
использованы после [сверки входов](evidence-reuse.json).

## Возможности

| Возможность | Статус | Основание / границы |
| --- | --- | --- |
| Snapshot заданного commit | passed | Новый [control](control-verification.json), прежние 16 acceptance scenarios; читаются tracked Git objects, не рабочая папка |
| Diff конечных A/B, полные изменённые файлы B | passed | [Acceptance](../operations-dependencies/acceptance-verification.json); обычный diff подтверждает только изменённые файлы |
| Strict baseline / неизменённые файлы | passed | Новый control: 1 analyzed/1 inherited, `baseline_verified`; несовместимый baseline даёт ожидаемый отказ 2 без fallback |
| Полный каталог прокси / отдельный словарь | passed с пределами качества | [77 NER/4 dictionary](../operations-dependencies/offline-verification.json), [46 direct parity](../operations-dependencies/scan-verification.json), runtime probe; техническое соответствие не равно полноте распознавания |
| JSON/HTML, полные значения/координаты/контекст | passed | Новый control, [installed CLI](../operations-dependencies/cli-verification.json); HTML renderer не менялся после [browser QA](../operations-stage-4/browser/browser-observations.json), нового browser-прогона в этапе 5 нет |
| Приватный output, безопасная консоль | passed / ожидаемые отказы | 0700/0600 в новом control; [extras](../operations-dependencies/extras-verification.json), unit: public/foreign/symlink/nonempty output отвергаются; ACL внешнего хранилища отдельны |
| Offline scan / контейнерная изоляция | passed | [25 Compose](../operations-dependencies/docker-verification.json), новый control; нет pull/build во время scan, код входного проекта не выполняется |
| Ошибки, timeout, OOM, cancel/cleanup | passed / ожидаемые отказы | [Faults](../operations-dependencies/fault-verification.json), [capacity](../operations-dependencies/capacity-verification.json), [cancel recovery](../operations-dependencies/cancellation.json); SIGKILL/потеря daemon требуют ручного точного cleanup |
| Fresh build / ready import / transfer | passed на том же Docker store | [Fresh](../operations-dependencies/fresh-walkthrough.json), [ready](../operations-dependencies/ready-walkthrough.json), [extras](../operations-dependencies/extras-verification.json); это не другой физический offline host |
| Раздельное обновление / откат | passed | [8 upgrade/rollback checks](../operations-dependencies/upgrade-verification.json); прежние images/locks сохранены, default автоматически не заменяется |
| Jenkins adapter | passed локально | Unit и extras проверяют argv/status/artifacts/0–1–2; реальный Jenkins controller не испытан |
| Остаточные native advisory | принято владельцем | [Четыре записи](../operations-dependencies/risk-acceptance.md) приняты для текущего комплекта в закрытом контуре; это не устранение библиотечных дефектов |

## Качество и ресурсы

На frozen synthetic code-v1: **TP 33 / FP 13 / FN 4**, exact precision **71.74%**,
recall **89.19%**. Есть известные пропуски/ошибки категорий/лишние срабатывания.
46/46 direct parity подтверждает соответствие прямому детектору, но не исправляет
эти ошибки. На 77 cases NER [detection drift отсутствует](../operations-dependencies/detection-drift.json).
Модель, пороги, словарь, разметка и corpus ради приёмки не менялись.

[Полный Requests](../operations-dependencies/public-requests.json), закреплённый
`b25c87d`: 132 объекта, 119 analyzed/13 unsupported/0 errors, 612 кандидатов,
exit 1 за 733.927 s на 8 CPU с analyze budget 1800 s и run budget 2400 s.
Без дополнительных excludes и выполнения кода клона; значения не проверялись
во внешних сервисах. У этого репозитория нет размеченного ground truth:
612 кандидатов не означают 612 действительных секретов или 100% recall.

[Семь capacity cases](../operations-dependencies/capacity-verification.json)
покрывают 10/100/1000 файлов, concurrency 2, 64 KiB текст, size-limit и множество
находок. Замеры ограничены конкретными inputs/budgets и интервалом sampler;
это не универсальные минимальные требования или SLA для 10 MiB текста.
Новый маленький control не повторяет измерение производительности.

## Платформы и инфраструктура

| Среда / решение | Статус | Что требуется |
| --- | --- | --- |
| CPU Linux ARM64 containers, Docker Desktop на Apple Silicon | passed | Именно этот комплект/платформа, доверенный non-root оператор и Docker daemon |
| Linux AMD64 / GPU | not-tested | Отдельные совместимые комплект/locks и проверки |
| Native Linux host, другой физический offline host | not-tested | Verify, контрольный scan, права/FS/resources/transfer на фактическом сервере |
| Реальный Jenkins controller, agents/RBAC/artifact retention | not-tested | Настройка владельцем CI и проверка на целевом job; пример не внедряет инфраструктуру |
| PKI, организационные proxy/registry/mirror policies | not-tested | Применить правила контура на стадии подготовки/переноса; scan не должен скачивать данные |
| Выбор целевого сервера/CPU/RAM/concurrency/timeouts | решение владельца | Измерить свою нагрузку; defaults 2 CPU/3g Analyzer, 1 CPU/1g scanner, run timeout 3600 s не являются SLA |
| Лицензия scanner / приватный vulnerability contact | решение владельца | [Лицензирование](../../docs/licensing.md), [SECURITY](../../SECURITY.md); решения и внешние настройки не принимались автоматически |
| Доверенные baseline, доступ/retention reports и backups | ответственность администратора | Полные значения чувствительны; 0700/0600 локальной FS не задают RBAC Jenkins/архива |

История между A/B, незакоммиченные файлы, LFS contents, содержимое подмодулей,
PDF/Office/OCR, архивы и растровые изображения вне области. SVG/XML могут
анализироваться как текст; визуального анализа нет. Неподдерживаемые/исключённые
объекты перечисляются в отчёте. Новый полный snapshot нужен после смены профиля;
ни один clean-результат не гарантирует отсутствие всех чувствительных данных.
