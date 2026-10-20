# Демонстрационный отчёт

[Открыть report.html](report.html) · [JSON](report.json).

Здесь только синтетические данные. JSON — точная копия
[контрактного snapshot-findings](../reports/snapshot-findings.json),
`artifact_kind=contract_example`. Коммиты/tree/images, подписи и score
иллюстративные; версия `0.0.0-spec` обозначает происхождение примера, не текущий
runtime. Это **не** результат реального клиента и **не** допустимый baseline.

HTML генерируется штатным renderer с постоянным баннером синтетического примера;
CSS/JS, экранирование и CSP остаются штатными. В dev-генераторе для одного вызова
подставляется validator, разрешающий только `contract_example` и выполняющий
полную schema/semantic validation с `allow_examples=True`. Production validator
и runtime не меняются, их отказ такому примеру проверяется отдельно.
Никакой фиктивный `scan_report` для генерации не создаётся.

```sh
.venv/bin/python scripts/check_documentation.py --write-demo
.venv/bin/python scripts/check_documentation.py
```

Без `--write-demo` проверка сравнивает существующие файлы с воспроизводимой
генерацией. Внешние assets/CDN не нужны. DOM/marker/ресурсы проверяются локально;
полная интерактивная проверка браузером относится к отдельному этапу приёмки.
Реальные чувствительные отчёты сюда не добавляются.
