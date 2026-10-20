# Первый релиз v0.1.0

Владелец 2026-10-20 разрешил финальное ревью/тестирование и публикацию при успешном
результате; явно выбраны обычный v0.1.0, MIT и два публичных GHCR images.
Задача: [#31](https://github.com/vovkins/ru-llm-scanner/issues/31).
Исходная точка — main `37d60ce`; предыдущая интеграция и её ограничения сохранены.

## Ревью

Проверены Git object/config/hook boundaries, clean baseline/profile/coverage,
атомарные private reports, HTML escaping/CSP, безопасная console summary,
Compose isolation/cleanup, pinned build inputs и публичный состав.
Detection/pipeline/schema не меняются: единственное изменение в `src/` — версия.
Новых блокирующих дефектов этих слоёв не обнаружено.

Изменения выпуска: версия/wheel metadata, MIT/сторонние notices, OCI labels,
копирование notices в verified contexts, готовый комплект и публикация через
временный Actions GITHUB_TOKEN. Новый manifest проверяет весь состав; перед
выполнением launcher на runner он сверяется с checkout. Извлечение архива запрещает
links/special files/traversal, push не заменяет stable tag другой image.
Добавлены шесть регрессий целостности и безопасного извлечения.

## Новые проверки конкретных образов

- [161 unit, 0 skipped](unit-tests.json), Black 82 файла, contracts и документация.
- [Raw/patched parity](analyzer-parity.json): 77 NER / 4 dictionary cases.
- [Installed CLI](cli-verification.json): 9 runs с baseline/profile/error/partial cases.
- [Scan/code-v1](scan-verification.json): 46/46 technical parity; независимые TP33/FP13/FN4 сохранены.
- [Production acceptance](acceptance.json): 16 runs, история/merge/кодировки/full-file,
  hostile config/hooks/replace/links, отсутствие неявного fetch, 7 чужих контейнеров сохранены.
- [Документация](documentation.json), [runtime lock](analyzer.runtime.lock.json),
  [точный deployment](deployment.json).

Analyzer runtime probe побайтово равен принятому dependency-кандидату: модель,
все runtime packages, dictionary и execution environment сохранены. Recipe/labels/
notices и source/image fingerprints новые; старый baseline автоматически не принимается.
Default locks/images не заменяются. Остаточные четыре native advisory остаются
[принятыми владельцем](../operations-dependencies/risk-acceptance.md), а не исправленными.

Полный Requests 119 analyzed/13 unsupported/0 error/612 findings, 478 upstream subset,
96 NER regressions, browser/capacity/fault/upgrade checks остаются предыдущими
свидетельствами, применимость которых ограничена неизменёнными входами/runtime.
Они не объявляются новыми прогонами. Raw отчёты публичного клона не публикуются.

## Завершение выпуска

Frozen offline bundle, соответствующие native sources, перенос/installed control,
GHCR pull/digests/public visibility и опубликованные assets проверяются отдельными
заключительными receipts в этой задаче. Подтверждённая исходная среда — Docker Desktop
CPU Linux ARM64; AMD64/GPU/Jenkins controller/PKI не объявляются проверенными.

Локальные заключительные gates пройдены:
[состав/сохранность](artifact-checks.json), [сборка/размеры/hashes](assembly.json),
[равенство runtime и границы изменений](build-proof.json),
[import → verify0 → snapshot0 → strict diff1 → invalid baseline2](bundle-control.json).
Основной архив — 1 421 170 414 байт, native-sources — 398 330 836 байт;
82 Debian source packages и CPython проверены по SHA-256.
Build source revision `9c92f6eec44a6ac94bf718003baa53e50ae242b2`; последующие
commits с receipts не меняют 106 runtime/build inputs frozen-комплекта.

[Независимый ARM64 runner control](runner-control.json) пройден;
[успешный workflow](https://github.com/vovkins/ru-llm-scanner/actions/runs/39477270345)
импортировал тот же архив и подтвердил version/verify/snapshot/strict diff/error.
[GHCR digests и анонимный pull](registry-images.json) обоих images проверены:
scanner `sha256:43221e25984eb1541109913b35cb3c3b2ec25a3048e4d7a9bb31af219e4dfba4`,
Analyzer index `sha256:dc9cacfba34f1145d977418bf20bb29e6ab8b7dbf5fcc19bb25babfdea6cc0dd`.
[14 deployment extras](extras-verification.json) включают installed private output,
Jenkins adapter codes/baseline rejection, transfer checksum и platform-ID rejection.
Настоящий Jenkins controller этим не проверен.

Первый workflow #39476857847 прошёл installed control, но остановился до push:
временный DOCKER_CONFIG терял выбранный daemon. Исправлен только workflow
(`set-host: true`, `293b601`); повторный запуск прошёл полностью.
Исходный image build — `9c92f6e`; финальный source bundle также получает
актуальные SECURITY/CONTRIBUTING/requirements и исправленную workflow-обвязку.
Сканирующие/build inputs и images остаются теми же; изменение состава docs
требует новой checksum архива, а не повторной сборки модели.

## Окончательный source/docs комплект

Предыдущие размеры/hash и registry receipt относятся к первому проверенному
frozen-комплекту и первому успешному push; они сохранены как исторические evidence.
Финальный архив включает обновлённые SECURITY/CONTRIBUTING/requirements и
исправленную workflow-обвязку: [состав](final-assembly.json),
[проверка inputs/сохранности](final-package-checks.json),
[повторный local import/control](final-bundle-control.json).
Source/docs snapshot — `b5889f0954fdeaca69c18af0d864bbc43864c832`,
исходная image build revision — `9c92f6eec44a6ac94bf718003baa53e50ae242b2`.
Все 106 runtime/build inputs равны прежним; images/wheel/native sources неизменны.
497 файлов, 1 421 176 669 байт; SHA-256 основного архива
`c88fcca1140f4d47f922e585e29ac5311f6a4469a4e336dace3693571ab50a6a`.

Финальная редакция отдельно прошла
[ARM64 workflow #39479189251](https://github.com/vovkins/ru-llm-scanner/actions/runs/39479189251):
[installed control](final-runner-control.json),
[итоговые GHCR digests/anonymous pull](final-registry-images.json),
[семь загруженных assets и серверные SHA-256 перед публикацией](final-assets.json).
Образы имеют те же digests, что при первом успешном push; stable tags не заменены
другим содержимым. Один сетевой read timeout GHCR успешно пройден повтором чтения;
новых изменений runtime или ослабления gates не потребовалось.

## Опубликованный результат

[Обычный релиз v0.1.0](https://github.com/vovkins/ru-llm-scanner/releases/tag/v0.1.0)
опубликован 2026-10-20, tag `e66b9e888948d038ee07446c5948fdca9376abcf`.
[Проверка публичной поставки](publication.json): anonymous GitHub API, все семь
ссылок и серверные SHA-256; основной архив и малые assets получены без credentials,
полный архив проверен по SHA-256 и импортирован. Шесть проверенных HTTP ranges
возобновили медленную первоначальную загрузку; полный digest совпал.
Native source asset проверен anonymous HEAD/серверным SHA-256 и ранее сверенным
локальным source closure (не объявляется повторным полным скачиванием).
Installed контроль скачанной копии: verify0/snapshot0/strict diff1/invalid baseline2,
private reports, неизменный вход и cleanup. Raw reports не опубликованы.
[Сохранность после публикации](post-publication-preservation.json): 7 чужих
контейнеров/их StartedAt, default locks/старые images, proxy/model/dictionary/corpus
сохранены; 65 unit hashes и все 106 inputs по-прежнему совпадают.
