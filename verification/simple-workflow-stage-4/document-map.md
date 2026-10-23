# Карта документации этапа4

Исходный checkpoint —4ef088b7475a51a8f5d74aee3b9b1ef50b253972 (#43, PR #44),
общий план #38, согласованный текущий этап #45. Main37e5e0e не меняется.

| Прежняя проблема | Основной документ после исправления | Сохранённый специальный путь |
| --- | --- | --- |
| README смешивал Make и ручной deployment | README: цель, предпосылки, три шага до отчёта, четыре команды | admin/advanced.md → опубликованные версии |
| Карта docs называла реализованные команды будущими | docs/README.md: user/admin/reference/development | verification сохраняет исходные checkpoints |
| Пользователь должен был получить lock и подготовить output | user/README.md: HEAD/commit, auto HOME/XDG output, optional OUTPUT | admin/explicit-launcher.md сохраняет прежние команды |
| Admin начинался с выбора архивов и промежуточных locks | admin/README.md → build.md: единый make build/test | admin/advanced-build.md сохраняет ручную CPU цепочку |
| Jenkins default deployment ошибочно выглядел общим | admin/jenkins.md: прямой CLI и точные коды | admin/jenkins-explicit.md и прежние примеры сохранены |
| Spec/development/runtime повторяли устаревшие статусы | reference/simple-workflow.md, everyday-tests.md и development.md согласованы | Raw CLI/explicit contracts подписаны отдельно |
| Различные ссылки вели к неверному виду build | installation/releases/Linux/scan API перенаправлены к соответствующим процедурам | Старые файлы-навигация остаются, historical evidence не переписан |
| Документы не проверяли публичные Make/CLI examples | check_documentation сверяет parser и Make names, defaults, links/shell/demo | Не объявляет browser/clean walkthrough своим результатом |

На основных страницах нет обязательных deployment/hash/wheel/engine шагов.
README/script changes входят в фактические build materials: для этого этапа
требуется новый native build. Остальные docs не изменяют detection fingerprint.
Механизм pinned proxyda4f50a, модель, словарь, зависимости, patches/locks, schema,
renderer и код Git/pipeline остаются прежними. Принятые native/certifi риски не исправлялись.

Native walkthrough читает помеченные shell blocks прямо из README/user guide,
без их отдельной копии в harness. Подготавливает только собственный synthetic
Git-клон (реальный git clone) с пробелами/Unicode; выполняет публичные команды,
отдельно проверяет коды, полный canary, private JSON/HTML, baseline и ошибки.
Ни в user-путь, ни в CI preparation не добавляется ручной venv/JSON/hash/wheel.
Установка системных Python/Docker в CI — явная подготовка хоста до первого запуска.

Статическая проверка сгенерированного HTML и просмотр браузером synthetic demo
учитываются отдельно. Новый настоящий Jenkins pilot и контролируемое proxy update
не входят в этап4; для них нужны следующие отдельные согласования.
