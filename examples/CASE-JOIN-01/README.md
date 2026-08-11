# CASE-JOIN-01: Regionalno potiskivanje spajanja

## Namjena

Različite SQL varijante iste ručno povezane analitičke namjere.

- `logical_question_id`: `trajectory_join_pushdown`
- deklarisana intervencija: `regional_pushdown_rewrite`
- rezultatska provjera: Uređeni i multiskupovni hash jednaki su prije i poslije preoblikovanja.

## Šta je opaženo

Join i agregacija prelaze sa GAC-a u regione. Regionalne grane vraćaju po 11 grupisanih redova umjesto miliona sirovih redova.

## Napomena o SQL-u

Predikat `mod(tenant_id, 1::bigint) = 0` namjerno je neselektivan. On je instancirana vrijednost parametra full-flow šablona i propušta svaki `tenant_id`; zadržan je jer pripada stvarno izvršenom SQL-u.

## Vremenski ugovor

Skup je generisan oko zamrznutog oslonca `2026-07-01T00:00:00Z` (`base_time_unix=1782864000`) sa verzionisanim sjemenom i prozorom od 30 dana. Kalendarski datumi u SQL-u su renderovani odmaci od tog oslonca, a ne datumi izvođenja eksperimenta. Tačni odmaci ovog slučaja zapisani su u `manifest.json`; mjereni SQL ne koristi `now()` ni `current_timestamp`.

`metrics.csv` sadrži medijane stvarnih ponavljanja. Direktorij `plans/` sadrži izvorne GAC planske artefakte, a gdje je relevantno i sanitizovane regionalne `auto_explain` planove sa stvarnim brojem redova i petlji. Potpuno porijeklo i SHA-256 izvornih artefakata zapisani su u `manifest.json`.

## Granica tumačenja

Ovaj slučaj dokumentuje opaženu tranziciju na evaluiranoj infrastrukturi. Ne predstavlja univerzalnu preporuku iste intervencije za drugi SQL ili drugu infrastrukturu.
