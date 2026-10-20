# Итоговая приёмка перед локальным пилотом

Этап [#25](https://github.com/vovkins/ru-llm-scanner/issues/25) общего цикла
[#16](https://github.com/vovkins/ru-llm-scanner/issues/16) явно согласован владельцем
2026-10-20. Результат относится к кандидату `e5e3115` поверх PR #29 и его
неизменным runtime-исходникам; сборочный checkpoint — `2588571`.
Ветка приёмки добавляет документацию и evidence. Версия — `0.1.0.dev0`.

## Заключение

**Кандидат готов к локальному пилоту в закрытом контуре на подтверждённой
платформе CPU Linux ARM64/Docker Desktop.** Существенные замечания имеют
исправление в кандидатах либо явное решение владельца. Новых блокирующих
продуктовых дефектов в проверенных границах итоговой приёмки не обнаружено.
Остаточные четыре native-риска [приняты владельцем](../operations-dependencies/risk-acceptance.md).
Это заключение не аттестует непроверенную инфраструктуру и абсолютную полноту
распознавания. [Матрица готовности и ограничений](readiness-matrix.md).

Результат подготовлен для review: `main` и штатный deployment сохранены.
Текущие PR не слиты; релиз, tags, registry и внешние настройки не изменялись.
Образы не пересобирались и не публиковались. Сохранены прежние комплекты для отката.

## Точный состав и применимость результатов

[Манифест кандидата](candidate-manifest.json) содержит head/base шести PR,
runtime/deployment/source hashes, wheel/schema, модель/словарь/spaCy/corpus,
дату advisory snapshot и результаты сверки. Стек:

[#19](https://github.com/vovkins/ru-llm-scanner/pull/19) →
[#21](https://github.com/vovkins/ru-llm-scanner/pull/21) →
[#23](https://github.com/vovkins/ru-llm-scanner/pull/23) →
[#27](https://github.com/vovkins/ru-llm-scanner/pull/27) →
[#28](https://github.com/vovkins/ru-llm-scanner/pull/28) →
[#29](https://github.com/vovkins/ru-llm-scanner/pull/29) →
[draft PR #30 итоговой приёмки](https://github.com/vovkins/ru-llm-scanner/pull/30).

| Компонент | Platform Image ID, Linux ARM64 |
| --- | --- |
| Analyzer | `sha256:40cb971b58e2144749080fd50e6cb5c7bad8b74ce2c4d237e8a9800165d7e8fc` |
| Scanner | `sha256:358e0664733bf571d510d23f213339661bcb8b4737c8eab322cc79f3f7ca7095` |

После сборочного checkpoint изменялись только docs/evidence. В этапе 5 заново
сверены 64 source files полного unit-прогона, 211 curated inputs Analyzer,
67 inputs scanner build и 21 установленный module/schema. Установленные engine
assets и build inventory совпали с lock; runtime probe Analyzer полностью
совпал с закреплённым runtime, включая модель и словарь. Build-only inventory
извлечён из незапущенного собственного контейнера; исполняемые probes выполнены
non-root/network-none/read-only. Приватные права inventory не ослаблялись.

Поэтому следующие успешные результаты повторно используются **по совпадению
входов**, без объявления новых прогонов: 155 host tests/0 skipped,
478 upstream subset, 96 NER regression, 77 NER/4 dictionary parity,
46 code-v1 direct parity, production/Compose/faults/extras/rollback/capacity,
fresh/ready walkthrough и полный Requests. Подробное основание каждого набора —
в [проверке применимости](evidence-reuse.json). Старый промежуточный build context
не использовался вместо фактического контекста принятого source checkpoint.

## Что выполнено в этапе 5

| Проверка | Результат |
| --- | --- |
| Стек, исходники, installed wheel/schema и runtime | [candidate-manifest.json](candidate-manifest.json) |
| Итоговое ревью и статусы замечаний | [review-matrix.md](review-matrix.md) |
| Минимальный installed offline-прогон | [control-verification.json](control-verification.json) |
| Contracts/schema/docs/help/links/shell/Black | [static-verification.json](static-verification.json), [documentation.json](documentation.json) |
| Сохранность ресурсов и cleanup | [preservation.json](preservation.json) |

Контрольный launcher скопирован в отдельную минимальную установку без `src/`,
dev venv и proxy. Он запускался Python со стандартной библиотекой (`-I -S`)
с явным deployment lock на том же Docker store:

1. `verify` → **0**: immutable IDs/платформа совпали.
2. Snapshot синтетического A → **0**, `snapshot_verified`: оба файла обработаны,
   находок/ошибок нет; его отчёт использован как доверенный baseline.
3. Strict diff A→B → **1**, `baseline_verified`: один файл обработан заново,
   один унаследован; синтетический пароль найден с полным значением, контекстом,
   координатами, категорией/источником/score и target commit в JSON/HTML.
4. Baseline для другого исходного коммита → **2**, `baseline_invalid`,
   `assurance=none`: скрытого перехода к обычному diff нет.

Проверены process/summary/report codes, безопасная консоль, права `0700/0600`,
неизменность input и cleanup каждого project. Сам прогон не измеряет новый SLA.
В локальном driver первоначально ошибочно ожидалось имя статуса `rejected`;
штатный контракт использует `invalid`. Все четыре runtime-команды уже прошли,
после исправления ожидания сохранённые артефакты повторно валидированы без
повторного запуска контейнеров. Это correction протокола, не дефект продукта.

Для повторения используйте [установку](../../docs/admin/installation.md) и
[strict diff](../../docs/user/README.md#5-проверить-переход-a--b): отдельный
синтетический клон, два файла в A, в B — `python-password` из frozen code-v1 в
одном файле, второй неизменён. Всегда выбирайте новые outputs. Полные reports
и raw logs сохранены приватно; в Git только безопасные сводки/hashes/counts.

## Решения после приёмки

Для отдельного решения о слиянии подготовлен стек выше и draft PR этого этапа.
Возможный порядок — от #19 к #29 и затем PR приёмки. При слиянии понадобятся
отдельное разрешение, проверка итогового main и корректировка bases оставшихся PR;
существующие результаты не объявляются проверкой ещё не созданного merge commit.

До запуска на целевом сервере администратор проверяет фактическую платформу,
ресурсы, Docker/FS, transfer/verify/control snapshot и свою нагрузку.
Jenkins controller/PKI, ACL/retention baseline и отчётов настраиваются отдельно.
Лицензия scanner и приватный vulnerability contact остаются решениями владельца;
они перечислены в [матрице](readiness-matrix.md), внешние настройки не применялись.
