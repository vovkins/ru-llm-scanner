# Подготовка v0.3.0

План [#51](https://github.com/vovkins/ru-llm-scanner/issues/51) согласован владельцем
2026-10-23, включая слияние проверенного релизного PR и публикацию после gates.
Сейчас выполняется подготовка; сборки/публичная приёмка ещё не завершены.

Исходная точка: main `70bdabb93efffb295e3e7596428c4aa859d2ea9d`.
Ветка `codex/release-v0.3.0`. Версия0.3.0, exact Analyzer9e47/logistic/APIv2;
model/dictionary/dependency/corpus pins сохранены. Меняются version labels и
соответствующие recipe hashes. Прежние релизы и их evidence не переписываются.

Релизная адаптация экспортирует images фактического Make build/walkthrough;
эти же IDs проходят direct Jenkins и остальные gates, замораживаются и
публикуются без пересборки. Исторический explicit import остаётся отдельной
проверкой совместимости. [Руководство выпуска](../../docs/admin/releases.md).

Сводки/run IDs/digests добавляются только после реального выполнения. Raw reports,
значения находок, environment, credentials и build cache не публикуются.
