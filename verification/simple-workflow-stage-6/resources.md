# Времена и ресурсы этапа 6

Полный run39848479099/source9f384a8, native Ubuntu 24.04, rootful Docker29.6.1,
non-root оператор, 4 CPU и около15.6 GiB RAM; диск перед запуском около107 GiB.
Это отдельная приёмка трёх установок, а не обязательная повседневная команда.
Точный набор, времена каждого шага и cgroup samples сохранены в native receipts.

| CPU | Весь этап, s | make test old / content / logistic, s | Requests, s |
| --- | --- | --- | --- |
| amd64 | 3198.816 | 84.188 / 84.105 / 84.1 | 1333.806 |
| arm64 | 2668.083 | 75.509 / 70.549 / 70.493 | 1307.674 |

Модельный probe ограничен4CPU/4GiB; память ниже — фактический cgroup memory.peak
этого probe, включающего real NER и оба raw/patched прохода. Dense — один case
с2500 повторениями, время patched ответа, не throughput произвольного репозитория.

| CPU | Peak old / content / logistic, MiB | Dense old / content / logistic, s |
| --- | --- | --- |
| amd64 | 892.5 / 802.7 / 803.1 | 1.5315 / 1.5405 / 1.7255 |
| arm64 | 814.8 / 833.5 / 834.2 | 1.2659 / 1.2726 / 1.4027 |

Requests использовал4CPU, прежние analyze timeout1800s и run timeout3600s.
Пределы не повышались ради успеха. Resource sampling раз в1s сохраняет наблюдённые
cgroup lifetime maxima; последний интервал может быть пропущен. Видимый /tmp не
включает удалённые открытые файлы и не является измерением полного disk peak.
Raw report HTML/JSON остаётся private; размеры и hashes сохранены без значений.

| CPU | Analyzer observed memory peak, MiB | Scanner observed memory peak, MiB | Private output, bytes |
| --- | --- | --- | --- |
| amd64 | 996.9 | 118.1 | 72524047 |
| arm64 | 1028.7 | 107.8 | 72524049 |

Все7 capacity cases на каждой CPU дали ожидаемые exit codes и cleanup:
10/100/100-concurrency2/1000 файлов, long64k, size-limit и many-findings128.
Настоящий OOM и отмена после первых находок вернули2; partial результат не
превратился в clean. Полные безопасные case receipts находятся в native JSON.

Jenkins AMD64 занял280.467s, включая контроллер и13 сценариев. Контроллер ограничен2GiB/1CPU,
agent работает отдельным native host process. По умолчанию пара scan-контейнеров
имеет3GiB/2CPU Analyzer и1GiB/1CPU Scanner. Для двух параллельных пар учитываются
8GiB лимитов плюс Jenkins, agent, Docker, ОС и запас; суммарный CPU делится
планировщиком. Эти лимиты и измерения не гарантируют SLA и не выбирают неизвестный
сервер владельца. GPU/rootless/corporate Jenkins/ARM64 Jenkins не проверены.
