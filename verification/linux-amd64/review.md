# Ревью Linux AMD64

Проверяемая реализация: `4c0d5dc5e01b2e98708e628eb49f97d5c4678760`.
[Итоговый native run](https://github.com/vovkins/ru-llm-scanner/actions/runs/39513865393)
успешен. [Итоговая матрица](readiness-matrix.md) фиксирует готовность и границы.

## Разобранные замечания

| Область | Решение и проверка |
| --- | --- |
| Смесь платформ/ABI | Общий allowlist CPU-платформ, wheel tags/METADATA/реальный ELF и Debian control; отрицательные тесты и проверка всех pinned artifacts |
| Нативность запуска | Проверка архитектуры Docker server до image lookup/run/import; чужая платформа возвращает `daemon_platform_mismatch`, import не меняет store |
| COPY при umask 077 | Права внутри images нормализуются явно, чтобы non-root читал код/модель/engine; production outputs сохраняют 0700/0600 |
| Linux test mounts и cleanup | Curated sources доступны UID 65534, synthetic QA exports удаляются другим UID внутри private host temp; отсутствующий Git helper включён в export-list |
| Пустая установка | Отдельные Docker и containerd process/socket/data root, пустой client config, images0/containers0 перед import; primary image store не меняется |
| Ранняя публикация результата Jenkins API | SUCCESS может появиться до завершения post/archive. Harness теперь ждёт `building=false`; регрессия воспроизводит early SUCCESS, реальная матрица содержит 13 завершённых сценариев |
| Baseline другого профиля | Валидный synthetic clean report с настоящим published ARM64 image identity отклоняется именно как `incompatible`; продвижения baseline при 1/2/ABORTED нет |
| Stale build metadata | Freeze сравнивает записанные inputs/runtime/deployment с checkout; старый native candidate отвергнут до создания пакета |
| Полный Requests | Одинаковые commit/tree/config/scope, coverage119/13/0 и 612 fingerprints; confidence tolerance1e-5 не скрывает изменения решений |
| Unit assets | Исторический source-only fixture/constraints отделены от новых image builds; полный unit не объявляется успешным при skipped |

Отдельный fork детекторов не создавался: source/model/dictionary общие,
архитектурные wheels/DEBs/base/runtime/deployment разделены. Изменения модели,
порогов и frozen corpus для прохождения тестов не вносились.

## Границы заключения

Подтверждения привязаны к своим build commits и immutable IDs. Документация,
CI triggers и безопасные evidence могут обновляться после тестирования при
неизменных runtime sources/pins. Это не заявление, что проверенный image заново
собран из нового документационного commit или что image tar побайтово воспроизводим.

Images/archives тестового AMD64 стенда остаются на disposable runner и не
публикуются. Для будущего релиза нужны новое отдельное согласование, versioned
сборка и проверки фактически публикуемых IDs. Опубликованный v0.1.0 сохраняется.

Измерения ресурсов относятся к выбранным fixtures/Requests и cgroup sampling,
не к доказанному минимуму/SLA для произвольного репозитория. Непроверенные
rootless/userns/другие CPU/ОС и другой физический закрытый сервер требуют пилота.

Четыре native-риска сохраняют прежнее решение владельца; исправленными они не
объявляются. Архитектурное system-libstdc++ исключение перепроверено на обеих
платформах, без утверждения об аттестации всех static wheel paths.
[Новый certifi advisory и proposal #34](certifi-advisory.md) рассматриваются отдельно;
patch не применён без решения владельца. Штатный offline Docker scan использует
внутренний HTTP и не делает внешних TLS-соединений.
