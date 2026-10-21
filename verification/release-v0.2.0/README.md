# Подготовка релиза v0.2.0

План [#36](https://github.com/vovkins/ru-llm-scanner/issues/36) явно согласован
владельцем 2026-10-21, включая release-tooling/version/docs, слияние релизного PR,
native AMD64/ARM64 builds/tests и публикацию после успешных gates.
Исходный main — `ee336f096305711e63cc352997e29aec36965193`.

Версия package/CLI/OCI labels —0.2.0. Детекторы/модель/словарь/corpus и pinned
Python/Debian dependencies не меняются. Старые v0.1.0/default deployments сохраняются.
[Решение certifi](../linux-amd64/certifi-advisory.md) и четыре native-риска остаются
принятыми в своих границах, исправление не заявляется.

Выпуск проходит build-release → frozen archives в draft → publish platform tags →
OCI indexes → anonymous native pull/control → обычный release → public assets/control.
Материалы #33 остаются reference; новые versioned IDs требуют новых проверок.
Образы до окончания disposable runner сохраняются в frozen assets, publisher их
не пересобирает. Общие index digests не подменяют platform IDs sealed metadata.

Этот source checkpoint фиксирует подготовку; новые runtime/registry/publication
результаты добавляются отдельно только после фактического прохождения.
[Получение и проверка комплекта](../../docs/admin/releases.md).
