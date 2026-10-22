# Руководство администратора

Подготовьте доверенный checkout scanner и хост, выполните `make build` и `make test`.
После этого пользователь запускает `make scan REPO=...` по
[своей инструкции](../user/README.md). Один и тот же процесс используется
на сервере с интернетом для сборки и на native CPU Linux AMD64/ARM64.
Во время scan интернет и внешние LLM/API не используются.

## Предпосылки

| Компонент | Требование |
| --- | --- |
| Host shell и инструменты | POSIX, Git, GNU Make 3.81+, `python3` версии 3.11+ с venv/ensurepip |
| Docker server | Rootful, Linux AMD64 или ARM64, API 1.49+, BuildKit с Dockerfile frontend 1.14+ |
| Docker CLI | Доступ к выбранному daemon, Compose v2+ |
| Оператор | Non-root, доступ к Docker и чтение клона, запись в checkout scanner и свои private каталоги |
| Файловая система | Scanner и bind-пути доступны daemon по тем же абсолютным путям, без ссылок в проверяемых путях |
| Сборочная сеть | Доступ к одобренным источникам Git, Python/OS packages, base image и модели |

Проверьте `python3 --version`, `git --version`, `make --version`, `docker version`,
`docker compose version`. На некоторых Linux для venv нужен отдельный системный
пакет. Установку системных инструментов выполняет администратор; scanner не
вызывает sudo и не переключает Docker context. Python 3.9 как `python3` недостаточен.

Docker-доступ привилегирован: агент и оператор доверенные. Контейнеры scanner
работают от UID/GID оператора. Rootless/userns-remap, GPU, SELinux/корпоративные
ACL и произвольные старые CPU в эту приёмку не входят. Удалённый daemon сам
не получает локальные файлы; общую файловую область проверяйте заранее.

Native reference — Ubuntu 24.04 AMD64/ARM64 в GitHub Actions, Docker 29.6.1,
Python 3.11. Docker Desktop на Apple Silicon проверялся отдельно в прежних этапах.
Для AMD64 проверялись EPYC/AVX2; фактический NumPy wheel требует x86-64-v2.
[CPU, ограничения и исторические измерения](linux-amd64.md).
Параметры целевого сервера/Jenkins ещё не выбраны; их пилот остаётся отдельным.

## Проверка установки и передача пользователю

1. Поместите доверенный checkout scanner вне проверяемого проекта и очищаемого CI workspace.
2. Из него выполните [сборку](build.md): `make build`, затем `make test` той же учётной записью на том же daemon.
3. Выполните контрольный scan собственного синтетического клона. Сверьте код, HTML/JSON и охват по [инструкции пользователя](../user/README.md).
4. Передайте путь установки и доступ к нему, подготовленный self-contained клон, при необходимости одобренный config/baseline вне входного проекта.
5. Определите владельца baseline и правила приватного хранения/retention. Автоматического продвижения baseline нет.

Комплект выбирается автоматически по Docker daemon, платформе и фактическим
build inputs; ручной deployment пользователю не передаётся. Внутреннее состояние
в `.build/workflow` приватно и принадлежит учётной записи сборки. Для другого
оператора подготовьте установку под его UID и daemon: автоматической передачи
прав или chmod нет. Старый explicit launcher доступен в [расширенном разделе](advanced.md).

## Ресурсы

Один scan по умолчанию ограничивает Analyzer **2 CPU / 3g**, Scanner **1 CPU / 1g**.
Это limits контейнеров, не доказанный минимум RAM и не резервирование.
`make test` в runtime-группе запускает **две пары контейнеров параллельно**;
сумма их memory limits — 8g, плюс место для ОС, Docker и host Python.
Параллельные jobs умножают бюджеты. [Точные параметры](../reference/simple-workflow.md#ресурсы-и-время).

На reference с 4 CPU и примерно 15.6 GiB доступной Docker памяти suite этапа3
занял 76–79 s. Peak RSS этого suite не измерялся. Это синтетическая проверка,
не SLA произвольного клона. [Протокол ресурсов](../../verification/simple-workflow-stage-3/resources.json).
Сборка требует дополнительного места для модели (~709 MB), cache, двух images,
contexts и предыдущего комплекта. Для начального серверного пилота ориентир —
20 GiB свободного tool-space **плюс** клон/отчёты; это запас, не измеренный минимум.
Ранние [размеры и capacity](linux-amd64.md#ресурсы-для-пилота) относятся к указанным там images.

## Сопровождение

[Повторная сборка и восстановление](build.md), [ошибки/cleanup/retention](operations.md),
[доверенный Jenkins](jenkins.md). Runtime использует private Compose, internal
network, read-only input/rootfs, non-root и отключённые Docker logs. Останавливаются
только ресурсы собственного запуска. Настройки daemon и чужие проекты не меняются.

[Обновление proxy](updating-analyzer.md) переносит применимые детекторы/словарь через
адаптер. Смена модели/правил/профиля требует нового clean snapshot для baseline.
[Сравнение и подготовка source-only кандидата](../reference/upstream-update.md) реализованы на этапе5 #38. Перенос exact9e47e65/logistic, настоящий откат и отдельный Jenkins AMD64 pilot проверены на [этапе6](../../verification/simple-workflow-stage-6/README.md); произвольное будущее upstream не принимается автоматически.
[Лицензия и notices](../licensing.md) передаются с комплектом.

Буквальное прохождение основных инструкций на чистых native AMD64/ARM64: [этап4](../../verification/simple-workflow-stage-4/README.md). Виды приёмки HTML/static/browser и ограничения указаны отдельно.
