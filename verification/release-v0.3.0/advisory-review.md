# Advisory review перед публикацией

Свежие native reports run39927948569 содержат140 Debian potential records вместо
139 у v0.2.0. Добавлен только `brotli 1.1.0-2 / CVE-2026-111497` в Scanner обеих
архитектур. Certifi/OSV IDs прежние; ранее принятые решения не пересматриваются.

[Debian tracker](https://security-tracker.debian.org/tracker/CVE-2026-111497)
считает эту версию уязвимой. Ошибка относится к разбору специально сформированного
Brotli-потока; upstream-исправление находится в декодере:
[Google Brotli patch](https://github.com/google/brotli/commit/0ed4268a4401abcb44720963).
Это новая запись, а не исправленная зависимость. Версии не обновляются скрыто.

По исходникам штатный reader запускает локальный Git с `GIT_NO_LAZY_FETCH=1`,
`GIT_ALLOW_PROTOCOL=''`, `protocol.allow=never` и без alternates. Он читает Git-объекты,
не HTTP-ответы и не распаковывает Brotli-файлы. Связь с Analyzer идёт через HTTPX,
который поддерживает Brotli только с optional decoder:
[HTTPX](https://www.python-httpx.org/quickstart/#binary-response-content).

Для окончательного disposition нужна проверка **фактического frozen Scanner** на
обеих CPU: optional modules/HTTPX encodings, ELF linkage самого Git и отдельного
HTTP-helper, process mappings после импорта CLI. Она добавлена в frozen-archive
workflow; helper `.github/release-probes/brotli.py` не меняет images или зависимости.
Все110 build/runtime material hashes сохраняются. Итог фактического измерения приведён ниже.

## Итог измерения

Frozen archive run39935005472 SUCCESS обеих CPU. [AMD64](amd64-brotli-reachability.json) и
[ARM64](arm64-brotli-reachability.json) проверили точные Scanner IDs принятого
комплекта, source5be9ad8 и общий probe SHA256cb820e3e73f92711f38f2613e6055b213d709013e170bdc7fb5ba8e0e340f5ae.

- Optional Python brotli/brotlicffi/_brotli отсутствуют; HTTPX поддерживает только identity/gzip/deflate и объявляет gzip,deflate. Синтетический ответ с br оставлен непрозрачным без декодирования.
- Основной Git не связан с libcurl/Brotli; отдельный git-remote-http связан с ними, но reader запрещает сетевые протоколы/lazy fetch и не запускает этот helper.
- После импорта настоящего CLI/HTTPX Brotli не загружен в Python process; Node отсутствует. Библиотека libbrotli1 1.1.0-2+b7 установлена и остаётся уязвимой.

Disposition: **vulnerable code not in supported execution path** для штатного
локального reader + внутреннего HTTPX. Это инженерное заключение с измеренными
основаниями, не исправление библиотеки, не новое решение владельца игнорировать
уязвимость и не исключение для произвольных программ/HTTP-запросов внутри image.
139 прежних Debian records побайтово совпали, новых PyPI advisory IDs нет.
Прежние четыре native риска и certifi-решение сохранены. В объявленном runtime
нет нового применимого blocker; при добавлении Brotli/другого transport нужна
повторная оценка. Само наличие advisory в стороннем image scanner не скрывается.
