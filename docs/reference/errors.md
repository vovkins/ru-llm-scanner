# Ошибки и действия

Коды завершения едины: 0 — завершено без находок, 1 — завершено с находками,
2 — ошибка/неполнота с приоритетом над находками. Ошибки не должны содержать
найденные значения, контекст, stderr или HTTP body. В report они привязаны
к этапу и при необходимости к файлу; в console launcher — только infrastructure code.

| Код/группа | Что проверить |
| --- | --- |
| `workflow_build_required`, `invalid_workflow_state` | Выполнить `make build` из доверенного checkout для выбранного daemon/platform; не редактировать generated manifests |
| `invalid_test_support` | Явным `make build` восстановить собственные test assets/environment, затем повторить `make test` |
| `unsafe_workflow_state`, `unsafe_workflow_directory` | Проверить owner/private permissions своих служебных путей; автоматического chmod/chown нет |
| `nonroot_operator_required`, `rootless_daemon_unsupported`, `unsupported_daemon_platform` | Non-root оператор, rootful native Linux AMD64/ARM64 Docker server |
| `docker_api_too_old`, `compose_version_unsupported`, `venv_unavailable` | Системные предпосылки из [admin](../admin/README.md), Python3.11+ как python3 |
| `invalid_arguments`, `config_error` | Обязательные refs/пути, режим, типы/ключи JSON, допустимые параметры |
| `invalid_lock`, `invalid_deployment`, `image_identity_mismatch` | Обычный bounded metadata file без final symlink, правильный deployment/platform и готовые локальные images |
| `daemon_platform_mismatch` | Архитектура Docker server не совпадает с deployment. Выберите полный комплект для этого daemon; автоматической эмуляции нет |
| `invalid_mount`, `unsafe_output`, `report_write_error`, `private_report_missing` | Отдельный output/parent, owner/private permissions, права Docker/UID mapping, место и квоту |
| `revision_unavailable`, `git_object_missing` | Нужные локальные commit/tree/blob; нет автоматического fetch |
| Ошибка layout/metadata Git | Self-contained clone, отсутствие alternates/external git-dir/ссылок/неподдерживаемого storage |
| `decode_error`, `encoding_conflict`, `file_too_large` | Явная кодировка/правила и лимит выбранного текста; профиль после изменения нужно проверить заново |
| `baseline_required`, `baseline_invalid`, `baseline_incompatible` | Доверенный clean A/tree/manifest/profile; при смене профиля новый snapshot |
| `engine_invalid_artifact`, `analyzer_profile_mismatch`, `analyzer_contract_error` | Выбранные engine/runtime assets, signature, API patch и фактический Analyzer |
| `analyzer_unavailable`, `analyzer_timeout`, `analyzer_failed` | Readiness/процесс/память/deadlines своего запуска |
| `scanner_failed`, `run_timeout`, `scan_cancelled` | Инфраструктурный отказ/отмена; доступные incomplete reports и budgets |
| `docker_unavailable`, `docker_command_failed`, `cleanup_failed` | Docker context/daemon/Compose, состояние ресурсов своего точного project |
| `jenkins_preflight_failed`, `jenkins_launcher_failed`, `jenkins_interrupted` | Trusted roots/workspace/status, строгий launcher summary и код, сигнал/cleanup |

Таблица группирует типовые ситуации и не является закрытым enum всех ошибок.
`reason` у excluded/unsupported — причина охвата, а не исключение, которое
можно считать проверенным. [Структура JSON](reports.md).

Повторяйте запуск в новом output только после исправления причины. При полном
отказе FS отчёт может отсутствовать; не создавайте пустой clean вручную.
Передавайте оператору код, project и обезличенную среду, не весь чувствительный
report. [Процедуры диагностики/cleanup](../admin/operations.md).
