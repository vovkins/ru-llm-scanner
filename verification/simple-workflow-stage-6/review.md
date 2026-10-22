# Ревью переноса и эксплуатационной границы

Ревью относится к этапу #49 поверх7045dd4. Результаты выполнения и точные sources
перечислены отдельно в [протоколе](README.md); этот документ их не заменяет.

| Область | Проверка и результат |
| --- | --- |
| Применимость upstream | Рассмотрены все25 changed paths, включая файлы вне прежнего export. 106 применимых sources закреплены по SHA; новые modules, шесть test files, настройки и коэффициенты включены. Proxy gateway/history/Redis/LLM routing не требуются scanner. |
| Граница адаптера | Новый API patch переносит metadata на exact server bytes. Стабилизация declaration rule_id выполняется после прежнего merge и не подаёт новые находки в merger. Она требует совпадения category/span и structural source, сохраняет NER/native metadata. AST regressions проверяют span/type/source/language и отсутствие мутации. |
| Публичный inventory API | Runtime probe читает health catalog, проверяет версию контракта, непустые уникальные строки и readiness; зависимость от приватного server alias удалена. Сам каталог и четыре источника сверяются с закреплённым upstream. |
| Unicode пути | Compose JSON сериализуется настоящим UTF-8: YAML parser отвергал surrogate escapes в emoji bind-path. Точный отказ и исправление воспроизведены отдельно, добавлена regression. Git reader и содержимое сканируемых файлов не менялись. |
| Исторический drift | Set-based дедупликация Presidio не учитывает rule metadata. Два старых rule_id-only расхождения допускаются только по явному решению владельца; новые metadata строго сравниваются. Прежние образы и результаты не исправляются. |
| Качество | Frozen code-v1 и Base64 добавка не менялись после измерений. Exact FP/FN публикуются, stress не считается независимой выборкой. Согласованная NER-overlap проверка дополнительно требует полного покрытия и точного сохранения прежних NER spans. |
| Jenkins | Прямой adapter переиспользует input validation прежнего adapter, использует process0/1/2 и отдельный status. Trusted installation/input/config/baseline расположены вне очищаемого workspace, параметры не интерполируются в shell. Console не является протоколом. |
| Test harness | Отрицательный Jenkins случай теперь действительно использует unbuilt installation. Docker observer связывает projects с WORKSPACE, запрещает acquisition и проверяет cleanup, не записывая raw argv. Его portable shebang проверен настоящим interpreter path с пробелом/emoji. |
| Повторная сборка | Candidate source-only probe и runtime probe различаются явно описанной проверкой metadata. Build receipts сохраняют реальные inputs/IDs. Clean walkthrough использует новый checkout/HOME, не копирует build state/venv и сверяет все material hashes. |
| Сохранность | Git reader, pipeline, report schema/renderer, model, dictionary, packages, прежние locks/patches/licenses/notices защищены проверкой хешей. Новая policy/source/patch меняют профиль явно, прежний baseline автоматически не принимается. |

Нерешённых замечаний к перечисленным изменениям исходников не выявлено.
Это не обещание автоматической совместимости будущего proxy: для него снова
нужны whole-tree review, точный candidate и применимые runtime/quality gates.
Известные FP/FN, невоспроизводимость обучения, принятые dependency-риски и границы
Jenkins/browser приёмки остаются явными ограничениями.
