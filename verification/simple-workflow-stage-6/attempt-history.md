# История попыток

Ни один неуспешный прогон не считается приёмкой. Root pin остаётся da4f50a до gates.

| Run / source | Результат и причина |
| --- | --- |
|39828164101 /754991d|Обе CPU остановились на old make build;106-source preparation прошла. Диагностика была недостаточной, новый детектор не запускался.|
|39828931605 /914dcaa|Обе CPU: build_smoke_failed. Образы старого механизма собраны, контрольный scan не прошёл; качество нового механизма не измерялось.|
|39829824719 /b9d9ac7|Обе CPU: повтор smoke дал docker_command_failed. Ошибка локализована в Compose, до нового алгоритма.|
|39830777807 /10d95d4|Обе CPU: old build/test244/real-model parity прошли; code-v1 TP33/FP13/FN4. New content build остановился в runtime inventory на приватном server alias `_KNOWN_SOURCES`.|
|39832756956 /9bbf6c6|AMD64: три build/test и реальные raw/patched model runs прошли; strict frozen verdict остановил дальнейшие gates на NER/Base64 fragmentation. Code-v1 logistic33/14/4, Base642511/3/1 (2500 повторений одного stress). ARM64: old build/test244/model и content build прошли; content make test отказал, подробная suite-диагностика добавлена в следующую попытку. Причина пока не установлена. Обе ветки run FAILED. |
|39835960260 /d59a69d|ARM64: три build/make test/model,489 Base64 tests,77-case real parity и полный old→logistic→old→logistic откат прошли. Walkthrough ошибочно вызван в уже собранной установке и сразу отклонён clean guard; fresh-run не выполнен. AMD64 ещё выполняется. Добавлены: добавлены независимое продолжение после измерения exact-расхождения и детальная диагностика failed make test. Final source ещё содержит прежний strict критерий; даже полный runtime pass не будет выдаваться за зелёный итог этого run. |

В отдельном кратковременном контейнере `/bin/true` воспроизведён точный отказ:
Compose YAML parser отвергает JSON surrogate-escape non-BMP символа в bind-path.
UTF-8 JSON (`ensure_ascii=False`) с тем же путём прошёл exit0. Добавлен unit
regression. Исправляется только host JSON serialization; Git reader, детекторы,
pipeline, схема и renderer не меняются. Старый checkout/образы не правятся:
исторический комплект в ASCII installation path; новые комплекты в paths с
пробелами/emoji. Общий rollback input содержит пробелы/кириллицу и совместим с
неизменным старым launcher. Все собственные контрольные контейнеры удалены.

Вторая ограниченная адаптация — `docker/probe_runtime.py`: catalog берётся из
публичного health payload, без зависимости от импортированного приватного имени
в server namespace. Локальная network=none проверка exact новых исходников на
готовом прежнем model/package closure прошла:30 categories/4 sources/logistic.
Это проверка inventory/import/model-file hashes, а не новая native image приёмка
или inference. Новые images должны быть действительно собраны/запечатаны.
Source-only candidate содержит historical probe из своего baseline; runtime
сборка сохраняет reviewed новый scanner metadata probe из ветки. Изменение
фиксируется отдельными before/after SHA,106 upstream sources/coefficients прежние.


Узкое [уточнение plain-container](criterion-amendment.md) отдельно согласовано владельцем после измерения. Разметка и exact categorical метрики сохраняются. Никакие другие пропуски/добавки этим не разрешены.

Walkthrough harness исправляется отдельным чистым checkout и private HOME.
Из уже проверенного logistic копируются только material inputs, их hash-map
сверяется полностью, фиксируется временный локальный candidate commit без remote
публикации. `.build`, venv/cache не копируются. Исходный clean guard не ослабляется.
