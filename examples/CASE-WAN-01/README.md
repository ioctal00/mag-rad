# CASE-WAN-01: Isti SQL nakon WAN intervencije

## Namjena

Isti SQL nakon deklarisane konfiguracijske intervencije.

- `logical_question_id`: `trajectory_aggregate_exact_full_flow`
- deklarisana intervencija: `wan_delay_10ms_probe`
- rezultatska provjera: Isti uređeni i multiskupovni hash u svih deset ponavljanja.

## Šta je opaženo

SQL i preneseni obim ostaju isti, dok RTT i čekanje na FDW granici rastu; time se transportna posljedica odvaja od promjene plana.

## Vremenski ugovor

Skup je generisan oko zamrznutog oslonca `2026-07-01T00:00:00Z` (`base_time_unix=1782864000`) sa verzionisanim sjemenom i prozorom od 30 dana. Kalendarski datumi u SQL-u su renderovani odmaci od tog oslonca, a ne datumi izvođenja eksperimenta. Tačni odmaci ovog slučaja zapisani su u `manifest.json`; mjereni SQL ne koristi `now()` ni `current_timestamp`.

`metrics.csv` sadrži medijane stvarnih ponavljanja. Direktorij `plans/` sadrži izvorne GAC planske artefakte, a gdje je relevantno i sanitizovane regionalne `auto_explain` planove sa stvarnim brojem redova i petlji. Potpuno porijeklo i SHA-256 izvornih artefakata zapisani su u `manifest.json`.

## Granica tumačenja

Ovaj slučaj dokumentuje opaženu tranziciju na evaluiranoj infrastrukturi. Ne predstavlja univerzalnu preporuku iste intervencije za drugi SQL ili drugu infrastrukturu.
