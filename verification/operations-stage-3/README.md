# Документация по ролям

[Этап #20](https://github.com/vovkins/ru-llm-scanner/issues/20) явно согласован
пользователем 2026-10-19. Исходная точка — `5ff130a`, исправления RV-01–RV-05
из draft PR #21. Этот этап меняет документацию, синтетические примеры и dev-проверку
их целостности; runtime/модель/профиль/штатные locks не меняются.

## Маршруты и источники

- [README](../../README.md) объясняет продукт и ведёт к двум ролям.
- [Пользователь](../../docs/user/README.md): готовый комплект → verify → snapshot →
  HTML/JSON → diff/baseline → настройки/ошибки/хранение.
- [Администратор](../../docs/admin/README.md): среда → import или fresh build →
  проверка/передача → operations/update/rollback/Jenkins.
- [Справочник](../../docs/reference/README.md): режимы, настройки, runtime,
  JSON/HTML, baseline, каталог/качество, артефакты и errors.
- [Разработчик](../../docs/development.md): API/dev tooling и явные asset-required группы.
- [Verification](../README.md): текущие и исторические evidence с границами.
- [Карта переноса страниц](navigation.md): прежние пути/входящие ссылки/новые источники.

DOC-01: fresh build проводит один `$RUNTIME_LOCK` после seal в parity, engine и
CLI, затем новый `$DEPLOYMENT` в verify/acceptance/export. Готовый пакет использует
свой deployment; export отдельно от launcher/docs. Jenkins example использует
стандартный путь lock своей trusted installation, поэтому его размещение явно
описано. Не требуется подставлять исторический image ID из Git для новой сборки.

DOC-02: README и карта показывают маршруты ролей; текст About подготовлен в
[docs/about.md](../../docs/about.md), внешние metadata не применены.
Старые doc paths остаются переходами. TEST-01 не объявлен исправленным:
unit без `.build/analyzer` может быть skipped; полный collector требует 0 skipped.

## Примеры и проверка

[Config](../../examples/config/scanner.json) соответствует `EffectiveConfig`.
[Demo HTML/JSON](../../examples/demo/README.md) генерируется из существующего
синтетического `contract_example`, без фиктивного `scan_report`. Dev-only scoped
validator допускает этот kind для одного вызова штатного renderer с полной
semantic validation; production validator продолжает отвергать его.
HTML содержит постоянную маркировку, штатные CSS/JS/CSP и не требует внешних assets.

Из dev environment:

```sh
.venv/bin/python scripts/check_documentation.py \
  --output .build/operations-docs/results/documentation.json
.venv/bin/python scripts/check_contracts.py
.venv/bin/python -m black --check scripts/check_documentation.py
git diff --check
```

`--write-demo` регенерирует только известный синтетический пример. Checker
сверяет defaults с кодом, разбирает примеры host/installed CLI реальными parsers,
проверяет flags build/integration через help, повторное использование lock и
состав HTML. Эти команды не запускают scan, Docker, build или установку пакетов.

Выполнена редакторская сверка обеих ролей с текущими source/help/locks и
существующим evidence. Это **не clean walkthrough** установки/сканирования и
не интерактивная browser acceptance. Реальная модель и full unit повторно ради
оформления документации не запускаются; их последнее отдельное evidence —
[этап исправлений](../operations-stage-2/README.md).

Подробный следующий план комплексного тестирования включает чистые каталоги,
целевые отказы, capacity/advisory/browser checks и требует отдельного согласования.
Merge/release/registry/лицензия/внешние settings этим этапом не меняются.

## Результаты этого этапа

| Проверка | Результат |
| --- | --- |
| [Documentation checker](documentation-verification.json) | 48 CLI/help-примеров, 19 defaults, 36 shell blocks с `bash -n`, 8 локальных anchors; новый runtime lock передан в 3 шага |
| Contracts | Schema валидна, 11 валидных synthetic reports и 22 отклонённых негативных случая; все локальные Markdown-ссылки разрешаются |
| Demo | 2 синтетические находки, `contract_example`, runtime отвергает пример; генерация воспроизводима, внешних assets нет |
| [Контроль границ](completion.json) | Existing non-Markdown/runtime/profile/locks/notices и прежние verification unchanged; source hashes сохранены |
| Редакторская проверка | Два последовательных маршрута, отдельные build/import/dev prerequisites, явные locks и Jenkins default path |

Инвентаризировано 19 прежних корневых docs-страниц, 10 paths стали переходами.
Black/diff checks прошли. Новых full unit/NER/production, браузерных или
нагрузочных результатов здесь нет. Синтаксическая проверка/парсинг аргументов
не выполняют команды примеров и не заменяют clean walkthrough.

[Следующий подробный план — #22](https://github.com/vovkins/ru-llm-scanner/issues/22),
53 чекбокса комплексного тестирования. Он ожидает отдельного явного согласования;
работа этапа 4 не начата.
