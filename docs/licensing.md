# Лицензирование и происхождение

Владелец выбрал **MIT** для ru-llm-scanner 2026-10-20 перед первым релизом.
Полный текст — [LICENSE](../LICENSE). Он включён в wheel, образы и офлайн-комплект.
Лицензии сторонних компонентов сохраняются; MIT scanner их не заменяет.

| Компонент | Происхождение и уведомления |
| --- | --- |
| Scanner | Copyright (c) 2026 vovkins, MIT |
| Analyzer/словарь | ru-llm-proxy `9e47e65` (logistic/APIv2); upstream README заявляет MIT; точные hashes и изменения — upstream.lock.json/patches |
| Правила Gitleaks | MIT, исходный copyright и текст сохранены побайтово в THIRD_PARTY_NOTICES.md |
| NER-модель | `fef2/ner_rus_bert-secret_detection`, revision `52b5b0745aac14f73fcf2ac0f91d9b5001a85ae4`, manifest объявляет Apache-2.0; шесть файлов неизменны |
| Python/native runtime | Собственные лицензии установленных зависимостей; notice files сохраняются в images |

[DISTRIBUTION_NOTICES](../DISTRIBUTION_NOTICES.md) содержит атрибуцию и ссылки,
[Apache-2.0](../licenses/Apache-2.0.txt) — полный текст лицензии модели.
Отдельного NOTICE в закреплённом комплекте модели нет. Дополнительные тексты
лежат вне её каталога и не меняют строгий model inventory.

Wheel включает license-files; образы — `/opt/scanner/licenses/` (Analyzer)
и `/opt/ru-llm-scanner/licenses/` (scanner). Лицензии wheels находятся также
в `*.dist-info`, Debian — в `/usr/share/doc` и `/usr/share/common-licenses`.
Release metadata содержит версии и hashes фактически установленных пакетов.

Рядом с бинарным офлайн-архивом публикуется архив `native-sources` с исходными
Debian source packages точных версий обоих образов, включая `.dsc`, original
tarballs и Debian patches/build recipes. Его manifest фиксирует HTTPS-источник,
размер и SHA-256 каждого файла; версии связываются с native inventory.
Это исходники для распространяемых системных компонентов, не новая сборка
scanner и не исправление принятых native advisory. Исходники CPython и
Docker Official Image recipe указаны в release metadata; собственные patches
scanner и curated upstream source включены в основной комплект.

Метаданные лицензий Analyzer можно получить без сети:

```sh
.venv/bin/python scripts/capture_licenses.py \
  --runtime-lock /trusted/build/analyzer.runtime.lock.json \
  --output .build/licenses-new.json
```

Inventory фиксирует объявленные SPDX expressions/classifiers и notice hashes.
Пустое поле означает отсутствие метаданных, а не отсутствие условий.
Исторические исследования: [dependency-кандидат](../verification/operations-dependencies/README.md)
и [upstream detection](reference/detection.md). Их старые записи «лицензия не выбрана»
описывают состояние до решения владельца и не являются статусом v0.1.0.
