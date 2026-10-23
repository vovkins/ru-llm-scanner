# Этап4: документация и чистый первый запуск

Согласованный этап [#45](https://github.com/vovkins/ru-llm-scanner/issues/45),
общий план [#38](https://github.com/vovkins/ru-llm-scanner/issues/38),
[draft PR #46](https://github.com/vovkins/ru-llm-scanner/pull/46).
База —4ef088b7475a51a8f5d74aee3b9b1ef50b253972 (#43/PR #44),
все PR #41/#42/#44/#46 остаются без слияния.

README и user/admin/build/Jenkins/reference дают единый путь
`make build` → `make test` → `make scan REPO=...` → приватные HTML/JSON.
[Карта изменений](document-map.md), [focused review](review.md).
Прежние explicit процедуры и опубликованный v0.2.0 доступны через
[advanced](../../docs/admin/advanced.md). Нового выпуска нет.

## Реальный native walkthrough

[39777325091](https://github.com/vovkins/ru-llm-scanner/actions/runs/39777325091),
точный source **63c2461789119773b01114f8fb51a12889b2fd89**, SUCCESS обеих архитектур.
[Метаданные запуска](native-run.json), [AMD64 receipt](native-amd64.json),
[ARM64 receipt](native-arm64.json), [103 material inputs](material-inputs.json).
Все103 hashes совпадают с текущей веткой; последующие evidence/docs-only changes
не требуют новой сборки и не перемещают source/images принятого прогона.

На каждом свежем Ubuntu24.04 runner (native CPU, Python3.11, rootful Docker29.6.1)
нет `.venv`, `.build/workflow` и прежних reports. Настройка системных Python/Docker
выполнена явно CI; пользовательский `make build` сам готовит остальное.
Harness создаёт synthetic seed и настоящий отдельный git clone с пробелами/Unicode,
читает **9 shell blocks из самих README/user docs**, фиксирует их hashes и
исполняет19 cases. Не вводятся ручные JSON/hash/wheel/venv preparation steps.

| Проверка | AMD64 | ARM64 |
| --- | --- | --- |
| Чистый checkout, missing installation → понятный make build | Passed | Passed |
| README make build → make test → scan HEAD | Passed | Passed |
| HEAD, явный commit, полный SHA, optional OUTPUT/CONFIG | Passed | Passed |
| Direct scanner1 / GNU Make2 при находке | Passed | Passed |
| Обычный diff changed_files_only / unverified | Passed | Passed |
| Clean snapshotA0, strict A/B1 с inherited/baseline_verified | Passed | Passed |
| Strict A=A0 / ошибочный baseline2 / недоступный ref2 | Passed | Passed |
| Непустой output2; приватные JSON/HTML0700/0600 | Passed | Passed |
| Повторный build: тот же выбранный комплект, acquisition0 | Passed | Passed |
| Полный synthetic canary в JSON/HTML, отсутствует в console | Passed | Passed |
| Input unchanged / internal network / non-root / RO / logs none / pull never | Passed | Passed |
| Cleanup всех22 own Compose projects, без broad cleanup | Passed | Passed |

Внутри make test: все **225 unit / 0 skipped / 0 missing**, шесть групп tools,
unit, contracts, documentation, format, runtime passed;9 собственных runtime
projects,2 параллельных scan, реальные model snapshot/diff/config/baseline,
timeout и SIGTERM2/cleanup. Полный Requests, новое качество модели, новый настоящий
Jenkins или proxy migration этим walkthrough не выполнялись.

[Ресурсы и времена](resources.json): Docker4CPU/~15.6GiB; весь walkthrough
389.997s AMD64 /337.329s ARM64; suite83.443s /75.462s. Peak RSS не измерялся.
Это не минимальная RAM и не SLA произвольного сервера/клона.

## Статические и browser проверки

[Local unit](local-unit-check.json):225/0skip/0missing.
[Документация](documentation-check.json):66 commands,55 shell blocks,19 прежних
analysis/runtime defaults плюс public HEAD/auto-output и Make names.
[Остальные checks](static-checks.json): contracts11valid/22negative, ссылки,
Black110files, git diff --check. [Fast CI](fast-run.json) прошёл отдельно.

Demo воспроизводится прежним renderer, помечен contract_example и отвергается
как runtime baseline. Сгенерированные native HTML проверены на cards/value/CSP
и отсутствие external assets. JSON/schema и packaged/public schema согласованы.

**Новый browser pass не заявлен.** Попытка открыть локальный demo через file://
отклонена URL policy браузерного инструмента; обхода не было.
[Точный статус](browser-status.json). Интерактивность/визуальная компоновка в этой
стадии не подтверждены браузером. Static HTML/schema/link checks и реальное
получение отчёта в чистом окружении перечислены раздельно.

## Сохранность и следующий шаг

[Preservation](preservation.json):45 protected inputs побайтово прежние, proxy
HEAD прежний,7 чужих контейнеров без изменения Running/StartedAt/Config,
69 прежних уникальных image IDs сохранены, v0.1.0/v0.2.0 identities/assets прежние.
Новые runtime images созданы только на временных CI runners и не публиковались;
Git main/release tags/GHCR не изменялись. Raw reports/build logs/models/env в
artifacts/evidence не включены. Native job имеет contents:read; release jobs skipped.

Этап5 — [#47](https://github.com/vovkins/ru-llm-scanner/issues/47): сравнение точных
ревизий proxy и подготовка отдельного кандидата. План ждёт явного согласования;
его реализация, принятие Base64 и новый Jenkins pilot не начаты.
