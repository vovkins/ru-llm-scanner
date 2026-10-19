# Эксплуатация и диагностика

Измерения ёмкости, реальные OOM/отмена и operator cleanup после SIGKILL:
[проверка #22](../../verification/operations-stage-4/README.md).
Состояние зависимостей и отдельный план до итогового допуска:
[DEP-01/DEP-02](../../verification/operations-stage-4/dependencies.md).

Основной запуск описан в [руководстве пользователя](../user/README.md),
состав/бюджеты — в [runtime](../reference/runtime.md).
Консоль launcher намеренно содержит только фиксированные коды и уникальный
`project`. Значения, refs, пути, контекст и HTTP bodies не печатаются. JSON/HTML
полные и чувствительные. Docker logs отключены; не включайте debug/HTTP logging
на продуктивном анализе для диагностики секретов. Локальные assertion logs
dev-проверок тоже нельзя автоматически публиковать.

1. Сохраните process code и технический project ID. Не печатайте входы/полный JSON
   и не включайте content logging ради диагностики.
2. Если console содержит infrastructure error, найдите его в
   [каноническом справочнике ошибок](../reference/errors.md): сначала проверьте
   выбранный deployment, Docker context/daemon, пути/UID и состояние собственного run.
3. Если код 2 без infrastructure error, прочитайте `errors`/coverage приватного
   JSON: ref/object/config/baseline, декодирование/лимиты или readiness/analysis.
   При отсутствии отчёта выясняйте ранний preflight/output/FS отказ.
4. Устраните причину и согласуйте нужные budgets/scope с владельцем. Новый scope
   или профиль требуют нового snapshot; память не исправляет FP/FN модели.
   Повторный запуск выполняйте в новый output, прежние результаты сохраните для разбора.

Даже при коде 2 часть находок может быть сохранена. Ранний отказ до scanner
или при недоступном output может не создать отчётов. Не подменяйте это пустым
clean report. Output writer атомарен для отдельного файла; consumer требует
exit 0 плюс доверенное происхождение/совместимость baseline.

## Потерянный запуск

Обычные SIGINT/TERM, ошибки и таймауты убирают собственные контейнеры/сеть.
После SIGKILL/перезапуска хоста/недоступности daemon выполнить cleanup из
прерванного процесса невозможно. Сопоставьте точный run ID из консоли, владельца
и отсутствие действующего процесса. Не удаляйте проект только по префиксу имени.

```bash
docker ps -a --filter 'label=com.docker.compose.project=rullmscan-EXACT_UUID'
docker network ls --filter 'label=com.docker.compose.project=rullmscan-EXACT_UUID'

# После проверки владельца/состояния — только перечисленные конкретные IDs:
docker rm -f EXACT_CONTAINER_ID_1 EXACT_CONTAINER_ID_2
docker network rm EXACT_NETWORK_ID
```

`docker system prune`, массовые stop/rm, удаление чужих networks/volumes и
автоматическое выключение других проектов не входят в launcher. Во время
приёмки действующие проекты не останавливались. Их Running/StartedAt сохранены.

## Ёмкость и доверие

Базовые budgets и проверенная среда указаны в quickstart. Лимиты RAM не означают
максимальный размер поддерживаемого репозитория: находки и renderer держат данные
в памяти. Длинные файлы/много находок требуют отдельного capacity test. Повышение
лимита не исправляет качество модели: известны FN/FP/ошибки категорий.

Входной object store не должен изменяться другим хостовым процессом во время
scan. Read-only bind защищает от записи из контейнера, не от владельца хоста.
Docker daemon и host operator доверенные; это не защита от администратора хоста.
Контейнеры не получают Docker socket, credentials, рабочее дерево в RW или
постоянный cache. Scanner возвращает код 2 при отказе обязательного сервиса.

Нет обещания транзакционной публикации двух отчётов, жёсткого времени CPU join,
обнаружения каждого секрета или приёмки неподдерживаемых Git layout/форматов.
[SECURITY](../../SECURITY.md), [результаты этапа 6](../../verification/stage-6/README.md).
