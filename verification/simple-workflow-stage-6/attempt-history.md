# История попыток

Ни один неуспешный прогон не считается полной приёмкой. Исторические результаты
сохранены; root pin меняется только после успешных gates.

| Run / source | Результат и причина |
| --- | --- |
|39828164101 /754991d|Обе CPU остановились на old make build;106-source preparation прошла. Диагностика была недостаточной, новый детектор не запускался.|
|39828931605 /914dcaa|Обе CPU: build_smoke_failed. Образы старого механизма собраны, контрольный scan не прошёл; качество нового механизма не измерялось.|
|39829824719 /b9d9ac7|Обе CPU: повтор smoke дал docker_command_failed. Ошибка локализована в Compose, до нового алгоритма.|
|39830777807 /10d95d4|Обе CPU: old build/test244/real-model parity прошли; code-v1 TP33/FP13/FN4. New content build остановился в runtime inventory на приватном server alias `_KNOWN_SOURCES`.|
|39832756956 /9bbf6c6|AMD64: три build/test и реальные raw/patched model runs прошли; strict frozen verdict остановил дальнейшие gates на NER/Base64 fragmentation. Code-v1 logistic33/14/4, Base642511/3/1 (2500 повторений одного stress). ARM64: old build/test244/model и content build прошли; content make test отказал, подробная suite-диагностика добавлена в следующую попытку. Конкретная причина этого отказа не установлена; в следующих прогонах он не воспроизвёлся. Обе ветки run FAILED. |
|39835960260 /d59a69d|ARM64: три build/make test/model,489 Base64 tests,77-case real parity и полный old→logistic→old→logistic откат прошли. Walkthrough ошибочно вызван в уже собранной установке и сразу отклонён clean guard; fresh-run не выполнен. AMD64 завершился тем же clean-checkout отказом после трёх комплектов,77-case parity и полного отката; обе CPU FAILED. Добавлены: независимое продолжение после измерения exact-расхождения и детальная диагностика failed make test. Final source ещё содержит прежний strict критерий; даже полный runtime pass не будет выдаваться за зелёный итог этого run. |
|39838784294 /52de7f2|ARM64 SUCCESS: три kits, model/upstream, реальный откат, чистый19-case walkthrough, scan/faults/seven capacity и Requests632/119analyzed/13unsupported/0error. AMD64 те же gates прошёл, отказ на logistic-jenkins; подробный child Jenkins receipt этой версии не экспортировался. Найден отдельный concrete harness defect: замена deployment path в новом шаблоне была no-op. Новый отрицательный сценарий проверяет unbuilt trusted installation/exit2 без reports. Docker argv observer дополнительно проверяет project cleanup и отсутствие acquisition без console parsing.|
|39841638737 /f12c798|API v2: ARM64 SUCCESS; AMD64 прошёл три комплекта, модели, откат, clean walkthrough, faults/capacity и Requests, затем отказал на Jenkins. Подробный child receipt ещё не экспортировался. Независимая сверка model/public scope прошла; полный run не считается успешным. Новые rule_id строго совпали, два historical-only drift записаны. |
|39846686884 /03cb872|Обе CPU отказали в content make test/unit до новых model runs: единственная ошибка test_docker_observer_tracks_cleanup_without_recording_arguments,261tests/0skip/1error. Причина локально воспроизведена через настоящий Python из пути с пробелом/emoji: абсолютный interpreter path в shebang разбивается ядром. Test observer и fake Docker переведены на /usr/bin/env python3; все261unit из того же space/emoji пути прошли. Модель/корпуса/коэффициенты не менялись.|
|39848479099 /9f384a8|Повторная полная приёмка с исправленными test shebang, отрицательным Jenkins сценарием и Docker observer; Jenkins выполняется до Requests. Обе CPU SUCCESS. Все gates, включая настоящий Jenkins AMD64, прошли; full cross comparison исходных успешных receipts — passed. Root source lock/API v2 приняты после этих gates.|

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

Независимая сверка run39835960260 показала rule_id-only drift в двух JSON случаях;
[расследование и конкретный прототип](metadata-review.md). Остальные поля2805
находок совпадают, max score delta3.3974647521972656e-06. Владелец отдельно согласовал historical-only исключение для двух точных случаев.
Metadata-only API v2 исправляет новый engine; все остальные поля и exact метрики
проверяются строго. Исторические образы не исправлялись.


Requests API v1 обеих CPU:632 findings, все612 исторических semantic identities
сохранены,20 добавок BASE64_DATA/base64.logistic-cascade в10 публичных paths;
изменений старых rule_id на Requests нет. Это не ground-truth secret precision.
Runtime v2 model/public scope подтверждён обеими CPU в39841638737; полный новый
Jenkins и финальное принятие source требуют результата39848479099.


После обнаруженных test harness дефектов Jenkins gate выполняется сразу после
трёх готовых комплектов, до долгого независимого Requests. Состав gates не
сокращён. Его safe receipt сохраняется и при отказе; raw логи не публикуются.
