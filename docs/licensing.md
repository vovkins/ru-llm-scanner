# Лицензирование и происхождение

Для dependency-кандидата #24 сохранён отдельный
[inventory фактически установленных пакетов](../verification/operations-dependencies/analyzer-licenses.json)
и [описание происхождения](../verification/operations-dependencies/README.md).
Исходные license/notice files wheels и Debian packages сохраняются в images.
Это inventory, а не выбор лицензии scanner или разрешение публикации.

В текущем checkout `ru-llm-scanner` нет файла LICENSE; лицензия scanner пока
не выбрана владельцем. Историческая read-only проверка GitHub 2026-10-18
также вернула `license=null`; это не новая проверка внешних настроек.
Не добавляем MIT/Apache badge или утверждение о лицензии без решения владельца.
Это статус проекта, а не рекомендация по юридическому толкованию лицензий.

## Исследованные источники

| Компонент | Проверенное основание | Дальнейшее действие |
| --- | --- | --- |
| `ru-llm-proxy` | README закреплённого SHA заявляет MIT; отдельного LICENSE в tracked tree нет | Уточнить достаточность уведомлений до распространения кода/образов |
| Правила из Gitleaks в прокси | `THIRD_PARTY_NOTICES.md` содержит MIT notice с авторством | Сохранить уведомление при переносе соответствующего компонента |
| NER-модель | `model_manifest.json` указывает `apache-2.0`; происхождение описано в прокси | Проверить и включить требуемые notices для фактических артефактов сборки |
| Python/runtime-зависимости | 71 пакет CPU ARM64 и метаданные уведомлений зафиксированы [инвентаризацией](../verification/stage-2/licenses.json) | Проверить комплект перед распространением |
| JSON Schema / проверка | Схема написана для scanner; `jsonschema[format]` — runtime/dev dependency | Отдельно учитывать лицензии распространяемых зависимостей |

Закреплённые ссылки: [инвентаризация upstream](reference/detection.md),
[уведомления прокси](https://github.com/vovkins/ru-llm-proxy/blob/da4f50a87ddf8a6c160c5f1893f5bf526f713d1c/THIRD_PARTY_NOTICES.md).

На этапе 1 не копировался runtime-код детекторов или веса. На этапе 2 источники
и веса используются в локальной сборке. [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)
сохранён побайтово из закреплённого upstream и включён в образ. Уведомления
установленных Python-пакетов сохраняются при копировании `/usr/local`;
их метаданные/хеши можно получить без сети:

```bash
.venv/bin/python scripts/capture_licenses.py \
  --runtime-lock /trusted/build/analyzer.runtime.lock.json \
  --output .build/licenses-new.json
```

Инвентаризация содержит объявленные SPDX expressions/classifiers и SHA-256
notice-файлов. Пустое поле означает отсутствие метаданных, а не отсутствие
условий использования. Веса имеют заявленную лицензию из model manifest;
отдельного license-файла в закреплённом комплекте модели нет. Выбор лицензии
scanner и окончательная проверка комплекта уведомлений перед распространением
остаются явными решениями владельца. Release/images не опубликованы, внешние
настройки/лицензия этим циклом документации не меняются. Побайтовый upstream
THIRD_PARTY_NOTICES сохраняется; ссылки на него и версии артефактов не являются
обещанием условий для ещё не выбранной лицензии scanner.
