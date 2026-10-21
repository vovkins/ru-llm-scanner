# Итоговая приёмка Linux AMD64

**Готов к контролируемому Linux AMD64/Jenkins пилоту в указанной среде.**
Полный native [run 39513865393](https://github.com/vovkins/ru-llm-scanner/actions/runs/39513865393)
успешен на source `4c0d5dc5e01b2e98708e628eb49f97d5c4678760`.
[Provenance и сверка 82 записанных inputs](candidate/provenance.json),
[результат workflow](candidate/run.json), [ревью](review.md).

| Область | AMD64 | ARM64 |
| --- | --- | --- |
| Стенд | Ubuntu 24.04.5, EPYC 7763/AVX2,4 vCPU,около16 GiB | Ubuntu 24.04.5,Neoverse-N2,4 vCPU,около16 GiB |
| Docker / Compose / image Python | 29.6.1 / 2.38.2 / 3.11.17 | 29.6.1 / 2.38.2 / 3.11.17 |
| Unit без skipped | 171 | 171 |
| Upstream core / NER | 478 / 96 | 478 / 96 |
| NER / dictionary parity | 77 / 4 | 77 / 4 |
| Code-v1 / installed CLI | 46 / 9 | 46 / 9 |
| Independent quality TP / FP / FN | 33 / 13 / 4 | 33 / 13 / 4 |
| Production / Docker / real faults / extras / Linux Git | 16 / 25 / 2 / 15 / 41 | 16 / 25 / 2 / 15 / 41 |
| Пустой отдельный Docker/containerd store | Import→verify0→snapshot0→repeat0→diff1→error2 | То же |
| Повторная cache-only/no-cache offline build | Inputs/runtime inventories совпали | То же |
| Полный Requests | 119 analyzed / 13 unsupported / 0 error,612 candidates,exit1 | То же |
| Полный Requests wall | 1330.392 s | 1381.503 s |
| Наблюдаемый RAM Analyzer / Scanner | 0.98 / 0.11 GiB | 1.01 / 0.11 GiB |
| Настоящий Jenkins | LTS2.580.1/51 plugins,13 завершённых сценариев | Adapter/runtime регрессия; отдельный ARM controller не проверялся |

Набор Requests совпал с прежним ARM64 reference и между архитектурами:
категории, значения, пути, координаты/контекст и source проверены через fingerprints.
Max cross-platform confidence delta `3.3974647521972656e-6`, заранее выбранный
допуск `1e-5`; изменившиеся решения этим допуском не скрываются. Ground truth
действующих секретов не устанавливался; внешней проверки значений не было.

AMD64 первый/повторный snapshot после import — 8.010/7.987 s.
Новые контейнеры, OS page cache не сбрасывался. Cgroup samples — 1 s polling,
последний интервал может быть пропущен, docker-exec probe добавляет overhead.
Это не минимум RAM, не physical disk peak и не SLA произвольного клона.

Проверенный AMD64 Scanner: `sha256:54500da9423aa4ddd77fbdf9acd0c234f8fdd91f713af1369c839fc48582a0d9`.
Analyzer platform ID: `sha256:23f0bb6ebd278bf2697a189717faaa0993241b47e557a906cb2a4c2f8faedb7f`.
Полные reference/platform IDs и runtime — в [build receipt](candidate/amd64/build-summary.json).
[ARM64 receipt](candidate/arm64/build-summary.json) хранится отдельно.

## Условия эксплуатации и сохранность

Rootful Docker с non-root оператором UID/GID1001; RO repo/rootfs, internal network,
private0700/0600, полные JSON/HTML значения и безопасная console проверены.
[Инструкция сервера](../../docs/admin/linux-amd64.md),
[Jenkins](../../docs/admin/jenkins.md), [установка](../../docs/admin/installation.md).
Rootless/userns-remap, другие ОС/CPU/PKI/ACL и физический закрытый сервер требуют
отдельного пилота. Параллельные jobs требуют суммы бюджетов и запаса хоста.

[Preservation](preservation.json): main/v0.1.0/default locks,proxy/model/dictionary/
corpus и 7 чужих контейнеров сохранены. [Старый release import/control](legacy-launcher-compatibility.json)
прошёл текущим launcher; исходный manifest не менялся.

Четыре native-риска приняты владельцем для закрытого контура и не исправлены.
System-libstdc++ исключение перепроверено на обеих архитектурах; static wheel
paths целиком не аттестованы. [Certifi #34](certifi-advisory.md) — отдельное
предложение, ожидающее решения; patch не применён. Версии dependencies сохранены.

## Поставка и последующие действия

Это неопубликованный кандидат, PR #35 остаётся draft и не слит.
Новые tags/releases/GHCR images/OCI indexes не публиковались. v0.1.0 остаётся ARM64.
Images/archives на disposable runner не обещаны доступными после job; перед
будущей публикацией нужны отдельное согласование, versioned build и проверки
реально публикуемых IDs. Не заявляется побайтовая воспроизводимость image tar.

Source images привязаны к build commit выше. Последующие docs/CI/evidence commits
сверены по неизменным runtime sources/pins; это не новая сборка проверенных images.
