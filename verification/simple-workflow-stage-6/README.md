# Этап6: перенос принятого logistic, откат и Jenkins

Задача [#49](https://github.com/vovkins/ru-llm-scanner/issues/49), общий цикл
[#38](https://github.com/vovkins/ru-llm-scanner/issues/38). Согласовано2026-10-22;
реализация и нативная приёмка выполняются в отдельной ветке. Ни один новый PR
не сливается, registry/release/tags не публикуются.

Переход на `logistic` принят владельцем по результатам исследования proxy.
[Ожидания до model runs](expectations.md) фиксируют проверки переноса, а не
повторное согласование алгоритма. Старый7045dd4/da4f50a и новый9e47e65 проверяются
в отдельных готовых установках content/logistic с неизменными dependencies,
словарём, моделью и коэффициентами. Текущий root pin пока прежний.

Повторная source preparation дала106 sources/0 blockers. Upstream PR104 merged
2026-10-21T19:20:10Z, base da4f50a, exact merge9e47e65. SHA256 source archive
08554f372dee79e51baaf8557457633b55aa2adaeb3916bfab5fb5564c9ad810 и module
59e2b297abfa23c11afe1076201271e0d0adbebf6625bd34e65c59bf5fa4be38 взяты из
закреплённой upstream документации; сам архив недоступен. Автор сообщает
генеративное происхождение без стороннего кода. Лицензии/notices/package/model
closure прежние; training inputs floating HEAD не позволяют воспроизвести обучение.

Новый [Jenkins adapter](../../examples/jenkins/run_workflow_scan.py) использует
прямой CLI и OS exit0/1/2, private output и отдельный status. Человеческая console
не является протоколом. Старый explicit adapter сохраняется. Настоящий Jenkins
pilot и model/native результаты пока не объявлены успешными.

Полные отчёты, environment, container logs и модель не публикуются. Native
workflow имеет contents:read и не вызывает release/registry jobs. Browser проверка
не заявляется: renderer не меняется, ранее file:// был заблокирован policy tool.
