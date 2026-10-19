# ADR-0006: изолированный Compose и владение жизненным циклом

Статус: принято планом этапа 6, реализовано 2026-10-19.

Scanner CLI и sealed Analyzer остаются отдельными образами. Online prepare
формирует явный context с закреплёнными/хешированными inputs; build работает без
сети. Доверенный deployment фиксирует reference и platform Image IDs. Import
сверяет пакет до load и фактические IDs после него. Поведение модели/словаря
не меняется ради контейнерной упаковки; новый Analyzer ID меняет analysis profile.

Launcher на стандартной библиотеке Python генерирует отдельный Compose JSON
в приватном временном каталоге: явные volumes/argv, escape `$` для Compose,
пустой env file, уникальный случайный project ID. Это позволяет безопасно
передавать пробелы/спецсимволы и исключить неявный config из сканируемого clone.
Все Docker-команды получают argv arrays, их сырой вывод не попадает в консоль.

Сервисы — non-root UID/GID оператора, root FS read-only, cap drop ALL,
no-new-privileges, tmpfs, CPU/RAM/pids budgets. Только общая internal network,
без ports/host network/socket/credentials. Scanner получает repo:ro, output:rw,
config/baseline отдельными ro mounts. Полные 0600 reports принадлежат оператору.
Container logging отключён; доступные отчёты — источник диагностики scan.

CLI ждёт readiness/signature, launcher наблюдает оба сервиса. SIGINT/TERM и
timeout отменяют scanner с grace на запись, затем удаляются только ресурсы
с точным project label. Infrastructure failure доминирует над прежним clean
артефактом: потребитель обязан учитывать exit всего запуска. Cleanup не изменяет
сами отчёты и не создаёт искусственный scan report при crash.

Границы: доверенный daemon/host, неизменность входного object store со стороны
хоста, отсутствие cleanup после SIGKILL/daemon loss, отдельная атомарность
JSON/HTML, неограниченная суммарная память результатов, нет абсолютного deadline
CPU join. SHA-256 не заменяет доверенное происхождение package/baseline. Проверен
CPU ARM64 на Docker Desktop; отдельный Linux-host/AMD64/GPU/Jenkins требуют своих
испытаний. [Руководство](../docker-quickstart.md) фиксирует проверенные лимиты.
