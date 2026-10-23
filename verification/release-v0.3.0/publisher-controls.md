# Отдельные проверки GHCR tags

Release image source остаётся `5be9ad8be41e5ccad36d4dcea2b1fe96d7d06c39`.
Publisher/verification workflows дополнены явным anonymous Docker pull каждого
`0.3.0-amd64`/`0.3.0-arm64` tag в дополнение к имеющимся общему tag, index digest
и platform digest. Их platform manifests сверяются с общим index, а фактические
image IDs и version/source labels — с installed control замороженного комплекта.

Изменены только два workflow-файла; все110 image/build material hashes совпадают
с release source. Это добавленная проверка распространения, не новая сборка
и не замена принятых images. Producer workflow SHA фиксируется отдельно от
image/source SHA. Настоящие результаты записываются после выполнения publisher;
наличие этого документа не означает, что публикация уже прошла.
