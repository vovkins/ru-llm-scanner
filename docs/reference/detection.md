# Механизм распознавания ru-llm-proxy

Инвентаризация выполнена по локальному чистому tracked-состоянию
`da4f50a87ddf8a6c160c5f1893f5bf526f713d1c` от 18 октября 2026 года.
Незакоммиченные `config/`, `secrets/` и `tmp/` не использовались.
Эта же ревизия закреплена в [source lock](../../upstream.lock.json); на её основе
собран и проверен CPU Analyzer для `linux/arm64`.

## Каталог

Источником является [entity_types.py закреплённой ревизии](https://github.com/vovkins/ru-llm-proxy/blob/da4f50a87ddf8a6c160c5f1893f5bf526f713d1c/presidio/entity_types.py).
Объединение детерминированного и NER-наборов содержит 30 типов:

| Группа | Типы |
| --- | --- |
| Имена и контекст | `PERSON`, `LOCATION`, `ORGANIZATION`, `CONTRACT_NUMBER` |
| Контакты и адреса | `PHONE_NUMBER`, `EMAIL_ADDRESS`, `RU_ADDRESS` |
| Документы и идентификаторы | `RU_INN`, `RU_KPP`, `RU_OGRN`, `RU_OGRNIP`, `RU_SNILS`, `RU_PASSPORT` |
| Банковские данные | `RU_BIK`, `RU_SETTLEMENT_ACCOUNT`, `RU_CORRESPONDENT_ACCOUNT`, `CREDIT_CARD` |
| Инфраструктура | `INTERNAL_IP`, `INTERNAL_DOMAIN`, `HOSTNAME`, `DB_URL` |
| Секреты | `JWT`, `BEARER_TOKEN`, `PRIVATE_KEY`, `BASE64_DATA`, `API_KEY`, `SECRET_KEY`, `AUTH_TOKEN`, `LOGIN`, `PASSWORD` |

NER покрывает `PERSON`, `LOCATION`, `ORGANIZATION`, `LOGIN`, `PASSWORD`,
`AUTH_TOKEN`, `SECRET_KEY`, `CONTRACT_NUMBER`. Некоторые категории имеют
несколько источников. Дополнительная категория scanner `DICTIONARY_TERM`
обозначает словарные бизнес-термины; это не новый NER-тип.

Модель: `fef2/ner_rus_bert-secret_detection`, ревизия
`52b5b0745aac14f73fcf2ac0f91d9b5001a85ae4`, SHA-256 весов
`6a2c875d02398554ec69384f489a0bf4fe3505fc347c6cdd3385d4fd31ef21a4`.
Источник: [model_manifest.json](https://github.com/vovkins/ru-llm-proxy/blob/da4f50a87ddf8a6c160c5f1893f5bf526f713d1c/presidio/model_manifest.json).
spaCy `ru_core_news_sm` и детерминированные правила также влияют на результат.

## HTTP-контракт

`POST /api/v1/analyze` принимает `text`, `language` (по умолчанию `ru`),
`entities` (`null` — все) и `score_threshold` (`0.35`). Возвращает исходный
`text` и массив `entities` с `entity_type`, `start`, `end`, `score`, `text`.
Смещения — в исходной строке Python, конец исключающий. Нельзя повторно
нормализовать текст или доверять ответу без проверки диапазонов и совпадения
`text[start:end]` с найденным значением.

`GET /api/v1/health` возвращает readiness, состояние/прогрев NER,
модель/ревизию, устройство, precision, batch size и `analysis_signature`.
Неготовность — HTTP 503; сканер требует `status=ok`, `ner_state=ready`,
`ner=loaded`, `ner_warmed_up=true` и ожидаемые модель/подпись. Смена подписи
во время запуска завершает проверку с ошибкой. Нет перехода к успешному
«только regex» при отказе обязательной NER-модели.

Проверенная реализация: [analyzer_server.py](https://github.com/vovkins/ru-llm-proxy/blob/da4f50a87ddf8a6c160c5f1893f5bf526f713d1c/presidio/analyzer_server.py).

## Источники и расширение API

Внутреннее `ru_llm_detection_source` принимает `ner`, `native_credential`,
`structural`, `contextual_contract`. `structural` — широкий класс
структурного распознавателя, не доказательство использования именно regex.
Нельзя угадывать источник по категории. `none` используется в диагностике
слияния, а не как источник валидной находки.

В исходном API эти метаданные не входят в HTTP-ответ.
[Отдельный патч](../../patches/analyzer-api-v1.patch) добавляет `source`, `rule_id`
и подпись `analysis_signature` в результат, а в health —
`scanner_contract_version=1`, `supported_entities` и `detection_sources`.
Если реального rule ID нет, возвращается `null`, без придуманного значения.
Новые категории/источники поддерживаются строками в JSON. Отсутствие
обязательного расширения — `analyzer_contract_error`, не молчаливый `unknown`.

Источник: [result_merging.py](https://github.com/vovkins/ru-llm-proxy/blob/da4f50a87ddf8a6c160c5f1893f5bf526f713d1c/presidio/result_merging.py).

## Настройки, подпись и словарь

В `analysis_signature` входят исходники Analyzer/NER/распознавателей,
модель/ревизия, версии пакетов и перечисленные upstream-переменные.
Подпись сама по себе не заменяет контрольную сумму весов, образа и словаря.

| Параметр профиля прокси | Исследованное значение Compose |
| --- | --- |
| `PRESIDIO_ANALYZER_DETECT_BARE_INN_BY_CHECKSUM` | `true` |
| `PRESIDIO_ANALYZER_DETECT_PUBLIC_IPS` | `true` |
| `PRESIDIO_ANALYZER_INTERNAL_DOMAIN_SUFFIXES` | `internal,local,lan,corp,corp.local,cluster.local,svc.cluster.local` |
| CPU profile / precision / batch size | `cpu` / `fp32` / `4` |
| GPU profile / precision / batch size | `gpu` / `fp16` / `8` |

Название `INTERNAL_IP` не означает, что публичные IP автоматически исключены:
это определяется настройкой. CPU/GPU и версии зависимостей фиксируются в
профиле, смена профиля требует snapshot. Значения по умолчанию отдельных
классов могут отличаться от Compose; сборка scanner закрепляет эффективный
профиль и проверяет его, не полагается на неявное окружение.

Прокси отдельно выполняет точные словарные подстановки до Analyzer.
[Словарь](https://github.com/vovkins/ru-llm-proxy/blob/da4f50a87ddf8a6c160c5f1893f5bf526f713d1c/litellm_guardrails/dictionary-substitutions.default.json)
содержит термины десяти банков. Scanner должен искать оригинальные `source`
с теми же настройками регистра/целой фразы из
[dictionary_policy.py](https://github.com/vovkins/ru-llm-proxy/blob/da4f50a87ddf8a6c160c5f1893f5bf526f713d1c/litellm_guardrails/dictionary_policy.py),
без замены исходного текста. Результат: `DICTIONARY_TERM`, `source=dictionary`,
реальный rule ID и `score=1.0` как точное выполнение правила, не вероятность.
Совпадение словаря может сосуществовать с NER-находкой в том же месте.

Политики шлюза, маскирование/восстановление ответа LLM, Redis mappings и
блокировка регулируемых тем не являются категориями сканирования файлов.
Полнота каталога не означает воспроизведение всех транспортных политик прокси.
У прокси synthetic allowlist по умолчанию выключен; новый скрытый allowlist
в scanner не добавляется. Существующие upstream-фильтры placeholder сохраняются.

## Качество

Переносим правила и профиль как единое закреплённое поведение. На этапе 2
сравнены 77 одинаковых текстов с исходным Analyzer и отдельно словарные
совпадения; пройдены 478 upstream-тестов. [Результаты и ограничения проверки](../../verification/stage-2/README.md).
На этапах 4–7 проверен независимый положительный/отрицательный корпус кода,
конфигураций и документации: [TP/FP/FN и ограничения](../../verification/stage-7/README.md).
Метрики прокси на запросах не являются метриками scanner.
Универсального выявления любых неизвестных/закодированных секретов нет.
