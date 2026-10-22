# Review реального Base64-обновления

[base64-review.json](base64-review.json) относится только к полным SHA
`da4f50a87ddf8a6c160c5f1893f5bf526f713d1c` →
`9e47e6594ba3d9616ba90720994ced008335416c` публичного ru-llm-proxy.
Это решение сопровождающего для **source-only кандидата**, не принятый runtime.
Не используйте его с другой ревизией или как автоматическую политику future main.

| Изменения | Решение и причина |
| --- | --- |
| analyzer_server, base64_data, json_strings, result_merging | Перенос полного применимого поведения; scanner metadata API адаптируется отдельно |
| Новый base64_logistic.py | Экспорт, включая фиксированные коэффициенты/пороги как часть source code; новых Python/NER artifacts нет |
| Новые evaluation/base64_policies.py и reports/base64-policies.json | Экспорт источника и публичного upstream evaluation record; его метрики не объявлены новым качеством scanner |
| Шесть новых presidio/tests/test_base64* | Экспорт всех regressions; source preparation их не исполняет |
| .env.example, docker-compose.yml | Adapter: явная candidate environment настройка вместо запуска Compose proxy |
| docs/README, base64-logistic, configuration | Proxy usage docs прочитаны, не нужны runtime; scanner guide описывает свою процедуру |
| .github workflow, Makefile | Proxy CI wiring; scanner сохраняет собственный Make/test и отдельную полную матрицу |
| tests/e2e и tests/test_ner_integration_config.py | Proxy Gateway/history/CI integration; не экспортируются в Analyzer, рассматриваются как reference этапа6 |

Все25 changed paths имеют before/after hashes и disposition/reason. Изменённые
13 применимых файлов под presidio переносятся;9 из них новые, итоговый экспорт106
вместо97. Словарь/NER model manifest/requirements/base/старые notices прежние.
Импорты и буквальные tracked resources проверяются также после patches.
Динамические связи и фактическая совместимость API остаются runtime gates.

Candidate явно выбирает `PRESIDIO_ANALYZER_BASE64_POLICY=logistic`; upstream default —
`content`. Текущий scanner lock/env не меняется. До принятия нужно сравнить оба
режима и зафиксировать ожидаемые различия качества/координат/нагрузки.

[Replacement API patch](patches/analyzer-api-base64-v1.patch) делает те же пять
metadata изменений, что прежний analyzer-api-v1.patch: category/source catalog,
analysis signature и finding source/rule ID. Он заново сформирован для точного
нового server bytes/offsets, без fuzz и изменения Base64 алгоритма. Три остальных
patches применяются побайтово прежними; до/после и patch SHA записаны в review.
Зависимость API adapter от exported entity catalog и внутреннего `_KNOWN_SOURCES`
осталась явной: её runtime совместимость нельзя доказать только import closure.

В новом модуле есть upstream-атрибуция происхождения коэффициентов/кода. License/
provenance проверка перед распространением остаётся отдельным gate этапа6;
неизменный THIRD_PARTY_NOTICES сам по себе не подтверждает новые условия.
Рабочий клон proxy, его конфиги/секреты и существующие deployments не изменяются.
[Инструкция инструмента](../../docs/reference/upstream-update.md).
