# Попытки релизной приёмки

- Native smoke39924875081/source4b1ddd2: SUCCESS обеих CPU. Прежняя атрибуция notices не влияет на подтверждённый CLI, но не принимается для новой поставки.
- Full release39926260316/sourcef4fb0fe: отменён до загрузки assets и до registry/tag/public Release. Причина — найденный при проверке licenses устаревший source commit в DISTRIBUTION_NOTICES.md/docs/licensing.md. Это не passed и не результат полной приёмки.
- Атрибуция исправлена до повторной сборки; upstream9e47 README заявляет MIT, THIRD_PARTY_NOTICES совпадает побайтово (SHA25679b0dc96e17376d526039c2a740d40c2e9da48f0a29a87770062e17d77493264). Детекторы/модель/словари/dependencies не меняются. Draft не содержал assets, поэтому замены принятых bytes не было. Новый полный прогон получает новый точный source SHA.
