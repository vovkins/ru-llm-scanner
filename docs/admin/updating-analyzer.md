# Обновление и откат Analyzer

Обычное обновление исходников scanner — [make build/test](build.md). Ниже — управляемая ручная подготовка **новой версии механизма** и историческая репетиция. Инструменты подготовки кандидата (этап5 #38) и реальное Base64-обновление (этап6) ещё не реализованы. Git reader/pipeline/renderer отделены от Analyzer; применимые изменения rules/NER/dictionary переносятся через закреплённый экспорт и адаптер. Маршрутизация LLM, Redis и восстановление ответов proxy в scanner не входят. Изменения API, новых модулей/настроек/зависимостей требуют явного сравнения и проверок, а не обещания автоматической совместимости любого будущего proxy.

Обновление — явное изменение закреплённых источников и артефактов, а не
переключение на `main/latest`. [Архитектура](../architecture.md) и
[ADR-0001](../decisions/0001-analyzer-boundary.md) задают границу механизма.

Для CPU AMD64 и ARM64 источники детекторов/модель/словарь остаются общими;
wheels/DEBs/base и runtime/deployment закрепляются отдельно. Выбирайте профиль
по [общему CPU-маршруту сборки](advanced-build.md), затем проверяйте обе архитектуры нативно
и сравнивайте решения. Нельзя переносить runtime lock или baseline между
профилями: после смены fingerprint нужен новый полный clean snapshot.

## Подготовка обновления

1. Выберите полный commit SHA прокси и изучите изменения правил, каталога,
   NER, словаря, API, Dockerfile и сторонних уведомлений.
2. В отдельной ветке обновите source lock: export-list и SHA-256 tracked-файлов,
   модельный manifest, patch input/output hashes, constraints и spaCy pin
   для нужной платформы. Проверьте источник новых артефактов; не копируйте
   незакоммиченный runtime/секреты из соседнего проекта.
3. Адаптируйте необходимые согласованные patches; NER/dependencies должны иметь
   собственное основание, before/after hashes и регрессии. Не копируйте полный
   upstream fork. Несовместимый patch завершает подготовку ошибкой.
4. Обновите полный artifact closure/hashes и inventory/notices. Выполните
   source `prepare`, offline context preparation, `verify-context`, `build` и `seal` по
   [руководству CPU-сборки](advanced-build.md). Старые lock/образы и отчёты сохраните для отката.

Source lock v1 хранит map `sources: path → SHA-256`. Каждый patch record содержит
хеш самого патча и `targets: path → {before, after}`. Build profile задаёт
платформу, CPU/GPU, базовый digest, путь/хеш constraints и `spacy_tree_sha256`.
Текущий CPU profile также закрепляет offline artifact lock и Dockerfile hash.
Само редактирование lock не подтверждает артефакт; доверенный источник,
сверка до/после и реальные проверки обязательны. Текущая версия инструмента
не содержит команды автоматического принятия новой модели или лицензии.

## Проверка перед принятием

- Запустите unit/контрактные тесты и тесты upstream с полным набором фикстур.
- Сравните непатченный и патченный Analyzer в одной среде. Новые поля API
  должны быть единственным отличием API patch. Если меняется NER, сравнивайте
  поведение отдельно: raw/patched с одинаковым NER проверяет только API parity.
- Прогоните реальную модель на согласованном корпусе, проверьте readiness,
  длинный текст, Unicode, словарь и негативные сценарии без сети.
- Проверьте provenance, лицензии и фактические файлы артефактов, обновите
  README, API-контракт, каталог, ограничения и результаты проверки.
- Зафиксируйте отдельный runtime lock с фактическим платформенным digest,
  локальной ссылкой запуска, пакетами, моделью и подписью. Не переносите
  digest старого образа в новый lock ради формального прохождения проверки.

Новые категории и источники перечисляются в health и ожидаемом runtime lock;
адаптер не требует нового закрытого enum. API scanner contract v1 обязателен.
Если upstream меняет API, исправляется ограниченный адаптер, не Git-логика.

## Baseline после обновления

После смены детекторов, артефактов, модели, влияющего профиля или scanner
semantics scanner требует новый полный snapshot проверяемого
состояния. Проверка только изменённых файлов новой моделью не подтверждает
неизменённые файлы. Прежний успешный baseline не объявляется совместимым
на основании одного имени модели. [Точные условия](../reference/baseline.md).

## Откат

Верните согласованные прежние source/runtime lock, патчи, профиль и готовый
образ. Проверьте его платформенный digest, readiness и подпись. Старый baseline
можно использовать только для правильного коммита и точно прежнего профиля.
Результат новой версии не становится совместимым автоматически.

## Проверенная историческая репетиция

На этапе 7 новая upstream-ревизия отсутствовала: main уже совпадал с закреплённым
`da4f50a87ddf8a6c160c5f1893f5bf526f713d1c`, остальные доступные ветки были его
предками. Пользователь явно согласовал настоящую историческую последовательность
**v0.4.0 (`dd403a182494a1c439f552666f21e7c4c8e7e080`) → da4f50a → v0.4.0**.
Это проверка реальных разных исходников, не имитация новой версии другим tag.

Исторический API patch добавляет те же metadata поля по пяти точным anchors;
отдельный patch и хеши до/после затем проверяются обычным `prepare` без fuzz.
Менялись словарная политика, LOGIN/instruction rules и result merging; модель,
runtime dependencies и third-party notices не менялись. Один и тот же scanner
wheel работал с обоими engine bundles. Git/pipeline/renderer не изменялись.

Пример повторения на том же CPU ARM64 окружении, с сохранённым source clone и
проверенным scanner context. Все выходные папки должны быть новыми:

```bash
python3 scripts/prepare_rehearsal.py \
  --source /path/to/ru-llm-proxy --output-dir .build/rehearsal

python3 scripts/analyzer.py build \
  --context .build/rehearsal/old-context --tag ru-llm-scanner-analyzer:rehearsal-old
python3 scripts/analyzer.py seal \
  --context .build/rehearsal/old-context --image ru-llm-scanner-analyzer:rehearsal-old \
  --output .build/rehearsal/old.runtime.lock.json
python3 scripts/prepare_scan_engine.py \
  --context .build/rehearsal/old-context --runtime-lock .build/rehearsal/old.runtime.lock.json \
  --output .build/rehearsal/old-engine

python3 scripts/build_rehearsal_scanner.py \
  --base-context .build/production-context --engine-dir .build/rehearsal/old-engine \
  --context .build/rehearsal/scanner-context --tag ru-llm-scanner:rehearsal-old \
  --deployment-lock .build/rehearsal/old.deployment.json

python3 scripts/check_upgrade_rollback.py \
  --old-deployment .build/rehearsal/old.deployment.json \
  --current-deployment locks/scanner-cpu-linux-arm64.deployment.json \
  --output-dir .build/rehearsal/transition
```

Это dev-инструменты с установленными зависимостями проекта; host launcher при
обычном scan по-прежнему использует только стандартную библиотеку. Исторический
helper намеренно закрепляет две согласованные SHA и отказывается от других
anchors/исходного lock. Для будущего нового upstream нужен новый reviewed source
lock/patch, а не изменение константы ради прохождения репетиции.

Проверки отдельного source lock больше не требуют временной замены штатного:

```bash
python3 scripts/check_rehearsal_parity.py \
  --context .build/rehearsal/old-context --runtime-lock .build/rehearsal/old.runtime.lock.json \
  --output-dir .build/rehearsal/parity
python3 scripts/check_cli_integration.py \
  --context .build/rehearsal/old-context \
  --source-lock .build/rehearsal/old-project/upstream.lock.json \
  --runtime-lock .build/rehearsal/old.runtime.lock.json \
  --scanner-image ru-llm-scanner:rehearsal-old --output-dir .build/rehearsal/code
```

`--source-lock` также поддержан dev scan harness. Raw/patched parity helper
монтирует только явный curated context и исходники проверки, без всего checkout.
Фиксируются 77/77 NER parity и четыре dictionary cases на каждой версии;
независимый code-v1 отдельно сохраняет прежние TP 33 / FP 13 / FN 4.

Восемь production шагов подтвердили: old baseline отвергается новой версией;
новый snapshot позволяет новый diff; после возврата точного старого deployment
новый baseline отвергается, старый baseline правильного B принимается, а baseline
другого A — нет. Повторный seal текущего образа полностью совпал со штатным.
Переключались явно выбранные отдельные deployment files; основные locks и клон
proxy оставались неизменными. Кандидат автоматически не принимается в эксплуатацию.
[Полные результаты и ограничения](../../verification/stage-7/README.md).
