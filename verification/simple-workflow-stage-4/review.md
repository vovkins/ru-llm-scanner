# Ревью документации и границ этапа4

Сравнение с4ef088b (#43): основные README/admin/user, канонический Make/CLI
справочник, dev prerequisites, CI entrypoints, example checker и новый native
walkthrough. Исторические verification не переписывались.

Проверено вручную по исходникам parser/config/state/launcher/schema:

- Первый путь требует системные инструменты и доверенный checkout; никакого ручного выбора wheel/engine/deployment/hashes. Python3.11+ именно как python3, non-root/rootful Docker и одинаковые bind paths описаны до build.
- Четыре операции и help сохранены. CLI scan означает snapshot с default HEAD/auto output; явные refs и resources не подменяются ambient Make variables. Отдельных setup/doctor/offline/up/down целей нет.
- README/user/admin показывают defaults HOME/XDG, private0700/0600 и новый/пустой OUTPUT; output permissions не исправляются автоматически. Полные значения только в приватных отчётах; console не является машинным протоколом.
- Прямые scanner0/1/2 отделены от GNU Make. Diff не сканирует промежуточную историю и не подтверждает неизменённые файлы без совместимого clean baseline. Coverage, assurance и доверенное происхождение описаны раздельно; promotion не автоматизирован.
- Rootful Docker, CPU/память/timeouts и limits отличены от измеренной ёмкости. Две пары контейнеров runtime-suite учтены; новый production server/Jenkins pilot не заявлен.
- Published0.1/0.2, текущий Make/CLI и внутренние raw entrypoints разделены в навигации. Прежняя ручная цепочка сохранена в advanced-build, explicit-launcher и jenkins-explicit; docs links/defaults/shell checked автоматически.
- Detector/Git/pipeline/report/schema/renderer, модель/словарь/версии/locks не менялись. Единственный runtime-file diff — удаление недостижимого текста о якобы неготовом make test; реализация команд прежняя.
- Native job имеет contents:read и отдаёт только безопасный receipt. Release jobs явно исключают documentation_walkthrough. Ни merge, ни registry/release/tags write не выполняются.
- Harness берёт команды прямо из помеченных docs blocks, работает только со своим synthetic clone/private outputs. После build Docker wrapper запрещает acquisition; проверки состава/изменений входа и own cleanup отделены от результатов модели.

Граница HTML приёмки: demo воспроизводится через прежний renderer и отклоняется
runtime как contract_example; сгенерированные native HTML проходят отдельную
структурную проверку CSP/assets/cards/value. Автоматическая попытка просмотра
локального demo через file:// заблокирована URL policy браузерного инструмента.
Обход не выполнялся. Интерактивность/визуальная компоновка в этой стадии браузером
не подтверждены; browser-status.json фиксирует not_performed, а не pass.

Применимые изменения proxy, конфликты patches, новые Base64 modules/settings,
паритет/качество новой версии и новый настоящий Jenkins относятся к этапам5–6.
Подготовленный план следующего этапа не является его реализацией.
