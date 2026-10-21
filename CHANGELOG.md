# Changelog

## 0.2.0 — 2026-10-21

- Добавлен CPU Linux AMD64; сохранена ARM64 поддержка.
- Два публичных GHCR packages получили общие `0.2.0` OCI indexes и явные
  `0.2.0-amd64`/`0.2.0-arm64` tags.
- Готовые offline-архивы каждой платформы включают launcher/docs/images/locks;
  публикация использует проверенные frozen images без повторной сборки.
- Полная native приёмка обеих архитектур, 13 сценариев настоящего Jenkins AMD64,
  полный Requests и post-publication anonymous download/pull/control завершены.
- Добавлены version/source/platform gates, безопасное извлечение архивов,
  immutable publication receipts и соответствующие native sources обеих платформ.

Модель, словарь, правила и версии dependencies сохранены; прежние принятые риски
не объявляются исправленными. Для нового runtime нужен новый полный clean baseline.
v0.1.0 и default deployments сохранены. [Протоколы](verification/release-v0.2.0/README.md).

## 0.1.0 — 2026-10-20

Первый выпуск локального сканера Git-репозиториев.

- Snapshot заданного коммита и diff конечных состояний A/B с полным анализом изменённых файлов.
- Доверенный совместимый clean baseline и строгий режим для подтверждения неизменённых файлов.
- NER, структурные/credential правила и бизнес-словарь из закреплённого ru-llm-proxy.
- Самостоятельные HTML/JSON с полными значениями, координатами, источником и score;
  приватный каталог отчётов и коды 0/1/2.
- Локальные Docker images CPU Linux ARM64, проверяемый offline transfer, stdlib launcher,
  документация пользователя/администратора и пример Jenkins.
- Исправления Git trust boundaries, lifecycle/coverage, NER window recovery и pinned dependencies,
  проверенные на синтетических корпусах и публичном Requests.
- MIT для scanner, сохранённые notices и происхождение сторонних компонентов.

Diff не проверяет промежуточную историю; некоммитированные файлы, PDF/Office/OCR,
архивы, содержимое LFS/подмодулей не анализируются. Нулевой результат не гарантирует
отсутствие всех чувствительных данных. Четыре native-риска приняты владельцем
для закрытого контура; исправленными они не объявляются.
