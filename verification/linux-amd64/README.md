# Linux AMD64 — итоговая нативная приёмка

План [#33](https://github.com/vovkins/ru-llm-scanner/issues/33) выполнен;
[draft PR #35](https://github.com/vovkins/ru-llm-scanner/pull/35) подготовлен к ревью.
Полный native [run 39513865393](https://github.com/vovkins/ru-llm-scanner/actions/runs/39513865393)
успешен для AMD64, ARM64 и compare. Реализация — source4c0d5dc; после неё
обновлялись документация/CI triggers/безопасные evidence при неизменных runtime inputs.

- [Матрица приёмки, ресурсы и ограничения](readiness-matrix.md).
- [Финальные протоколы и provenance](candidate/provenance.json):171 unit на каждой
  архитектуре,478/96 upstream,77+4 parity,46 scan/9 CLI,TP33/FP13/FN4,
  production16/Docker25/faults2/extras15/LinuxGit41,offline empty-store0/1/2.
- [Настоящий Jenkins13](candidate/amd64/jenkins-verification.json): completed builds,
  valid foreign image baseline,cancel/timeout/agent-loss recovery,private artifacts.
- [Сравнение NER](candidate/cross-platform.json) и
  [полного Requests](candidate/public-cross-platform.json):119/13/0,612 candidates,
  exit1; решение совпало с исходным ARM64 reference, tolerance1e-5.
- [Ревью](review.md), [stale-input negative](stale-input-rejection.json),
  [сохранность](preservation.json), [compatibility v0.1.0](legacy-launcher-compatibility.json).
- [Проверенные AMD64 inputs](inputs.json):132 artifacts, все SHA/размеры,
  wheel metadata/ELF и Debian control; версии сохранены.
- [82 corresponding native sources](native-sources.json) и
  [существующий исходный архив](native-source-reference.json). Модель/словарь/patches/
  corpus не изменены. Architecture-specific system-libstdc++ исключение проверено
  заново; прежние четыре риска не объявлены исправленными.
- [Решение по certifi #34](certifi-advisory.md): владелец 2026-10-21 сохранил
  версии для штатного offline Docker-маршрута с ограничением HTTPS вне него;
  подготовленный patch не применялся, исправление пакета не заявляется.

Промежуточные initial-native-amd64/native-progress и прежние comparison receipts
сохраняют собственные commits/runs; не подменяют финальный candidate. В ходе
нативной приёмки исправлены umask/COPY permissions,Linux test mounts/cleanup,
Git helper export,отдельный containerd store и ожидание Jenkins post/archive.
Подробности — в ревью и истории #33.

Полные реальные отчёты,credentials,images/model archives и cache не публиковались
как CI artifacts. Новый release/tag/GHCR push и merge не выполнялись.
Публичный v0.1.0 остаётся ARM64; для будущей публикации требуется отдельное решение.
