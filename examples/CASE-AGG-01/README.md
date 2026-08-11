# CASE-AGG-01: Ponovljeni agregacijski upit i provjera povrata

## Namjena

Ponavljanje istog SQL-a u kompatibilnom kontekstu.

- `logical_question_id`: `trajectory_aggregate_exact_full_flow`
- deklarisana intervencija: `restore_origin`
- rezultatska provjera: Isti uređeni i multiskupovni hash u svih deset ponavljanja.

## Šta je opaženo

Povrat konfiguracije reprodukuje početni fizički profil; mala razlika trajanja ostaje unutar unaprijed definisanog mjernog šuma.

## Vremenski ugovor

Skup je generisan oko zamrznutog oslonca `2026-07-01T00:00:00Z` (`base_time_unix=1782864000`) sa verzionisanim sjemenom i prozorom od 30 dana. Kalendarski datumi u SQL-u su renderovani odmaci od tog oslonca, a ne datumi izvođenja eksperimenta. Tačni odmaci ovog slučaja zapisani su u `manifest.json`; mjereni SQL ne koristi `now()` ni `current_timestamp`.

`metrics.csv` sadrži medijane stvarnih ponavljanja. Direktorij `plans/` sadrži izvorne GAC planske artefakte, a gdje je relevantno i sanitizovane regionalne `auto_explain` planove sa stvarnim brojem redova i petlji. Potpuno porijeklo i SHA-256 izvornih artefakata zapisani su u `manifest.json`.

## Granica tumačenja

Ovaj slučaj dokumentuje opaženu tranziciju na evaluiranoj infrastrukturi. Ne predstavlja univerzalnu preporuku iste intervencije za drugi SQL ili drugu infrastrukturu.
