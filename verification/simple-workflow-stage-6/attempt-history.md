# История попыток

Ни один неуспешный прогон не считается приёмкой. Root pin остаётся da4f50a до gates.

| Run / source | Результат и причина |
| --- | --- |
|39828164101 /754991d|Обе CPU остановились на old make build;106-source preparation прошла. Диагностика была недостаточной, новый детектор не запускался.|
|39828931605 /914dcaa|Обе CPU: build_smoke_failed. Образы старого механизма собраны, контрольный scan не прошёл; качество нового механизма не измерялось.|
|39829824719 /b9d9ac7|Обе CPU: повтор smoke дал docker_command_failed. Ошибка локализована в Compose, до нового алгоритма.|

В отдельном кратковременном контейнере `/bin/true` воспроизведён точный отказ:
Compose YAML parser отвергает JSON surrogate-escape non-BMP символа в bind-path.
UTF-8 JSON (`ensure_ascii=False`) с тем же путём прошёл exit0. Добавлен unit
regression. Исправляется только host JSON serialization; Git reader, детекторы,
pipeline, схема и renderer не меняются. Старый checkout/образы не правятся:
исторический комплект в ASCII installation path; новые комплекты в paths с
пробелами/emoji. Общий rollback input содержит пробелы/кириллицу и совместим с
неизменным старым launcher. Все собственные контрольные контейнеры удалены.
