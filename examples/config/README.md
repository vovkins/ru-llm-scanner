# Пример внешней конфигурации

[scanner.json](scanner.json) содержит текущие значения по умолчанию без secrets,
локальных адресов организации или автоматических исключений. Проверка
`scripts/check_documentation.py` сверяет его с `EffectiveConfig` и загрузчиком.

Скопируйте пример в доверенный каталог **вне** проверяемого клона и передайте
`--config /trusted/scanner.json` явно. Администратор контролирует доступ к файлу.
Для Docker URL Analyzer всё равно фиксирован внутренним runtime.

Изменения include/exclude/encoding/size/score меняют профиль и совместимость
baseline. [Правила, defaults и приоритет](../../docs/reference/configuration.md).
