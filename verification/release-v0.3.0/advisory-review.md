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
Все110 build/runtime material hashes сохраняются. До её завершения вывод о
недостижимости декодера и допуск публикации не сделаны.
