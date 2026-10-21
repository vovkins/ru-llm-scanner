# Релиз v0.2.0: протоколы приёмки

План [#36](https://github.com/vovkins/ru-llm-scanner/issues/36) согласован владельцем
2026-10-21, включая слияние PR #37 и публикацию после успешных проверок.
[Обычный GitHub Release v0.2.0](https://github.com/vovkins/ru-llm-scanner/releases/tag/v0.2.0)
и оба публичных GHCR packages опубликованы. Полное скачивание архивов без credentials,
анонимный pull по tag/index/child и installed control прошли на обеих native платформах.
[Получение и установка](../../docs/admin/releases.md).

## Происхождение

Build/source commit: `246ff4304cf5868888949e5bd9b5c4938a60191e`.
[Полная сборка и приёмка](https://github.com/vovkins/ru-llm-scanner/actions/runs/39623117010)
и [проверка скачанных архивов](https://github.com/vovkins/ru-llm-scanner/actions/runs/39632190783)
завершились успешно на native Ubuntu 24.04 AMD64/ARM64. Все 85 material inputs
совпадают с этим source. Позднейшие CI/docs/evidence commits не означают пересборку
образов. Publisher импортирует эти же frozen bytes.

[Build validation](build-validation.json), [связь sources/runtime](source-and-runtime-equivalence.json),
[итоговая приёмка](release-acceptance.json), [протокол CI](native-run.json),
[финальные архивы](final-archive-run.json).
В `native/amd64/` и `native/arm64/` сохранены безопасные summaries конкретных сборок;
`final-archive-control/` содержит проверки полного скачанного `.tar.gz`, OCI metadata
и установки в отдельный пустой Docker/containerd store. Primary store не изменён.

## Результаты новых образов

| Проверка | AMD64 и ARM64 |
| --- | --- |
| Unit | 186, без skipped; 21 release regression |
| Upstream / parity | 478 core, 96 NER; 77 NER + 4 dictionary parity |
| Scan / installed CLI | 46 / 9 |
| Independent quality | TP 33 / FP 13 / FN 4; прежние ограничения сохранены |
| Production / Docker / faults / extras / Linux Git | 16 / 25 / 2 / 15 / 41 |
| Изолированный import/control | verify 0, snapshot 0, repeat 0, strict diff 1, invalid baseline 2 |
| Полный Requests | 119 analyzed / 13 unsupported / 0 errors, 612 находок, exit 1 |

Настоящий Jenkins AMD64: 13 завершённых сценариев, включая cancellation/timeout/
agent-loss recovery, несовместимый baseline и приватные артефакты. Боевой Jenkins
не менялся. Requests проверялся без исполнения его кода; ground truth секретов
отсутствует. Конфигурация, coverage и все решения совпали с принятым reference;
максимальная разница confidence между CPU — `4.5299530029296875e-06`, допуск `1e-5`.
[Cross-platform](cross-platform.json), [Requests comparison](public-cross-platform.json).

| Новый Requests run | AMD64 | ARM64 |
| --- | --- | --- |
| Wall time | 1204.479 s | 1329.290 s |
| Наблюдаемый Analyzer memory peak | 1035898880 B | 1108287488 B |
| Наблюдаемый Scanner memory peak | 114278400 B | 112410624 B |

Это измерения выбранного дерева при 4 CPU и timeout 1800 s, не минимум/SLA любого
репозитория. Cgroup polling выполнялся раз в секунду; последнее окно могло быть
пропущено. Temp-file sampling не является пиком диска. Другой физический сервер,
CPU flags, rootless/userns и корпоративные ACL/PKI требуют целевого пилота.

## Архивы

| Архив | Размер | Полная SHA-256 |
| --- | --- | --- |
| `ru-llm-scanner-v0.2.0-linux-amd64.tar.gz` | 1515530716 B | `ac0fd101c0b6aad534f0ddac82f206dbc11f3d4930c8946665ff8e5b9a74f21a` |
| `ru-llm-scanner-v0.2.0-linux-arm64.tar.gz` | 1421520971 B | `a8437f065957e8f64b1e922271bb7aa9620c17ed6e42246a82dd85d0248a7f97` |

Один wheel обеих сборок побайтово одинаков. Общий native-source archive покрывает
82 Debian source packages и CPython обеих фактических runtime inventories.
[Wheel extraction](wheel-extraction.json) проверяет весь wheel из bounded prefix,
а не выдаёт это за полное скачивание архива на host. Полные архивы скачаны и
проверены на обоих native runners.

Встроенные `frozen_release_candidate`/`images_published: false` — факты момента
заморозки. Они не переписываются после публикации; текущая доступность определяется
GitHub Release и отдельными registry/publication receipts. OCI version/source labels
проверены; build revision связан manifests/receipts, стандартный OCI revision label
не заявляется. Index, platform manifest и config ID различаются.

## Риски и сохранность

Модель, словарь, детекторы и Python/Debian pins сохранены. Изменение source lock —
только recipe hash обоих профилей из-за OCI version label 0.2.0.
Свежие audits обоих actual runtimes: четыре OSV alias matches одного уже принятого
certifi advisory, 139 Debian potential tuples без новых CVE/source versions.
[Разбор](advisory-disposition-basis.json),
[решение certifi](../linux-amd64/certifi-advisory.md) и
[четыре native-риска](../operations-dependencies/risk-acceptance.md) не являются
исправлениями библиотек. Принят штатный offline Docker route с внутренним HTTP;
произвольный HTTPS raw CLI требует отдельной оценки. Aligned-new exclusion проверен
на actual ELFs обеих архитектур; полного attestation всех статических wheel paths нет.

v0.1.0, его tags/digests/assets, default deployments, proxy/corpus и чужие контейнеры
сохраняются. Реальные отчёты, credentials, host configs, model/images и cache в Git
не включены. Ранние preliminary/legacy протоколы ниже относятся к своим checkpoint,
не заменяют приёмку новых versioned образов.

## Публикация и контроль доставки

[Publisher run](https://github.com/vovkins/ru-llm-scanner/actions/runs/39634197749)
проверил четыре platform images, создал два OCI indexes и выполнил anonymous native
pull/control. [Post-publication run](https://github.com/vovkins/ru-llm-scanner/actions/runs/39635295581)
скачал полные публичные `.tar.gz`, сверил SHA256SUMS и повторил native pull/control
без credentials. [Registry mapping](registry-images.json), [provenance](release-provenance.json),
[SHA256SUMS](SHA256SUMS), [public run](public-run.json), [финальная сохранность](preservation-final.json).

`anonymous-registry/` и `public-release/` содержат реальные контрольные протоколы
обеих архитектур. Git tag v0.2.0 указывает на build/source246ff43; documentation-only
receipts в main добавлены позже и не меняют поставленные bytes. Все 19 assets
проверены по серверным digest/size; основные архивы фактически скачаны полностью
без авторизации на native runners. Native-sources архив проверен локально целиком,
его публичная доступность подтверждена отдельно; отдельного полного повторного
скачивания 400 MB native-sources после публикации не заявляется.
