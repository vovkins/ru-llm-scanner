# Повседневные проверки

Из доверенного checkout scanner:

```sh
make build
make test
```

Нужны те же Python3.11+/Git/Make/Docker/Compose и non-root доступ, что для
[сборки и scan](simple-workflow.md). Build может использовать интернет и сам
готовит Python-инструменты и source-only unit fixture. Test использует уже
проверенный локальный комплект и не устанавливает пакеты, не получает Git-исходники,
не скачивает модель и не собирает/загружает образы. При missing/stale/corrupt
installation, environment или assets возвращает2 и предлагает `make build`.

| Группа | Что выполняется |
| --- | --- |
| tools | `pip check` в собственном закреплённом build venv, без install |
| unit | Все обнаруженные unit; обязательные CLI/dictionary/config/Git/pipeline/report/upstream/workflow группы, без skips |
| contracts | JSON Schema, валидные и отрицательные примеры, локальные ссылки |
| documentation | Параметры/defaults, shell syntax, навигация, demo/CSP |
| format | Black `--check`; исходники автоматически не изменяются |
| runtime | Настоящая модель: snapshot/HEAD/diff/strict baseline/invalid baseline, Make CONFIG/resources, parallel scans, timeout и SIGTERM |

Ожидаемые scanner0/1/2 — результаты отдельных synthetic cases. Например,
найденный тестовый пароль с code1 означает успешный case. Общий `./scanner test`
возвращает0 только после всего suite,2 — при отказе, неполноте или отмене.
GNU Make возвращает свой код ошибки рецепта; для автоматизации доступен прямой CLI.
Пустое discovery, отсутствие обязательной группы и любой skip не являются pass.

Каждый запуск получает private `.build/workflow/tests/<random>/`, отдельную копию
проверенного historical unit fixture, synthetic repo, JSON/HTML и logs.
Консоль содержит имена групп, итог, время и путь диагностики. Найденные значения,
сырые unit traces, HTTP body, env и container logs туда не выводятся. Summary JSON
в этом каталоге содержит только безопасные counts/statuses, но доступ сохраняется
приватным. Отчёты и assertion logs автоматически в CI не публикуются.

Historical ARM64 source-only fixture нужен старым HTTP-stub/unit контрактам.
Его source/runtime locks сохранены; это не ARM64 inference на AMD64. Настоящие
runtime cases используют текущие образы native платформы. Глобальный
`.build/analyzer` не перезаписывается; ручная подготовка для `make test` не нужна.
Standalone developer unit по-прежнему может использовать прежний explicit путь.

Build проверяет состав Python environment и unit materials по hashes. Повреждённый
собственный cached environment заменяется новым после проверки; старые каталоги
не удаляются автоматически. Повторный исправный build переиспользует runtime images.
Test сам восстановлением или acquisition не занимается.

SIGINT/SIGTERM останавливает собственные дочерние процессы; cleanup использует
только Compose project identifiers, записанные private wrapper этого запуска.
Параллельные tests/scans имеют разные каталоги и проекты; builds одного daemon
сериализуются. Для parallel runtime cases одновременно запускаются два Analyzer,
поэтому нужен дополнительный запас RAM по сравнению с одиночным scan.
Фактическое время/ресурсы нативной проверки фиксируются в протоколе этапа #43;
это не performance SLA для произвольного сервера.

Полный Requests, upstream/independent quality, release archives/GHCR и настоящий
Jenkins/migration остаются отдельной полной матрицей CI. Повседневный suite не
подменяет эти gates. Новые команды ещё не входят в опубликованный v0.2.0.
