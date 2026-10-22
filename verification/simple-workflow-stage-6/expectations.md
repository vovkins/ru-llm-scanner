# Зафиксированные ожидания до model runs

Этап #49 согласован 2026-10-22. Выбор `logistic` уже принят владельцем на основании
исследования proxy. Эти проверки выявляют ошибки переноса и эксплуатации scanner.
Начальный scanner7045dd4, old da4f50a, new9e47e65; коэффициенты/пороги не изменяются.

| Сравнение | Ожидание |
| --- | --- |
| old → new/content | Сохранены прежние защиты; новые исправления JSON/typed spans перечисляются отдельно |
| new/content → new/logistic | Дополнительные BASE64_DATA для закодированных контейнеров без чувствительного decoded content; это расширение политики |
| raw → patched при той же policy | Идентичные category/start/end/value/score, допускается только дополнительная scanner metadata |
| AMD64 ↔ ARM64 | Идентичные решения, координаты, значения (SHA256), source/rule; score abs delta ≤1e-5 |
| Native credentials/NER | Категории и защищённые spans не теряются из-за cascade; различия требуют объяснения/исправления интеграции |
| Baseline | Старый baseline отклоняется новым профилем; новый clean snapshot разрешает strict diff; rollback принимает только совместимый старый baseline |

До запусков добавлен [base64-update-v1](../../tests/corpus/base64-update-v1.json):
независимые synthetic значения, разметка по конструкции исходного текста, явный
scope Base64/native filters, включая2500 dense values через outer chunks. Все
размеченные защиты и отрицательные случаи должны совпасть точно. Нельзя менять
пороги/разметку после результатов ради pass. Прежний code-v1 неизменен; его TP/FP/FN
измеряются отдельно (исторически33/13/4), новые BASE64 различия объясняются явно.
Публичный Requests не имеет ground truth и не измеряет истинность секретов.

Ресурсные бюджеты до запусков: обычные CLI tests штатные limits; Requests4CPU,
analyze1800s/run3600s, как в прежнем опубликованном измерении. Synthetic model probe
4CPU/4GiB/1800s; dense2500 API ≤120s, без OOM/partial. Capacity/stress отдельны от
SLA; измеряются wall time и cgroup peak/samples, для параллельных jobs суммарный
лимит учитывается отдельно. Никакого скрытого повышения budgets/exclude ради clean.

Новые коэффициенты — source code, runtime packages/NER/model/dictionary прежние.
Upstream PR104 сообщает генеративное происхождение; исходный архив публично не
доступен, training inputs floating HEAD, обучение побайтово не воспроизводилось.
Это ограничение происхождения сохраняется; upstream training metrics не являются
независимой оценкой scanner.
