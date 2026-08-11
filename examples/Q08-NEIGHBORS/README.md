# Q08-NEIGHBORS: tačni SQL identiteti analize greške

Ovaj katalog dokumentuje ciljni upit `q08_tenant_avg` iz N3 faze B i pet susjeda iz N3 faze A koji su korišteni u procjeni. Svi upiti prvo povezuju EU, US i APAC granu pomoću `UNION ALL`. Tabela navodi instancirane vremenske granice, `LIMIT` vrijednosti i primarni ključ sortiranja; SQL datoteke čuvaju i determinističke sekundarne ključeve.

Datumi su izvedeni iz zamrznutog oslonca skupa `2026-07-01T00:00:00Z`, a kolona `cutoff_offset_days` u `query-index.csv` čuva njihov relativni odmak. Oni nisu vezani za datum pokretanja eksperimenta.

| ID | Uloga | Analitička namjera | Granica | Odmak | K | Poredak |
| --- | --- | --- | --- | --: | --: | --- |
| [`q03_event_recent`](queries/q03_event_recent.sql) | neighbor | 250 najnovijih događaja nakon granice vremena | `2026-06-24 00:00:00+00` | 7 dana | 250 | `created_at DESC` |
| [`q04_event_oldest`](queries/q04_event_oldest.sql) | neighbor | 500 najstarijih događaja nakon granice vremena | `2026-06-17 00:00:00+00` | 14 dana | 500 | `created_at ASC` |
| [`q05_event_deviation`](queries/q05_event_deviation.sql) | neighbor | 50 događaja s najvećim odstupanjem abs(value - 500) | `2026-06-30 00:00:00+00` | 1 dana | 50 | `abs(value - 500) DESC` |
| [`q06_tenant_sum`](queries/q06_tenant_sum.sql) | neighbor | 100 region-tenant grupa s najvećim SUM(value) | `2026-06-29 00:00:00+00` | 2 dana | 100 | `SUM(value) DESC` |
| [`q07_tenant_count`](queries/q07_tenant_count.sql) | neighbor | 250 region-tenant grupa s najvećim COUNT(\*) | `2026-06-24 00:00:00+00` | 7 dana | 250 | `COUNT(*) DESC` |
| [`q08_tenant_avg`](queries/q08_tenant_avg.sql) | target | 500 region-tenant grupa s najvećim AVG(value) | `2026-06-17 00:00:00+00` | 14 dana | 500 | `AVG(value) DESC` |

## Trag procjene

- `q08_neighbors.csv` sadrži udaljenosti, težine i stvarne dobitke susjeda.
- `q08_action_rankings.csv` sadrži procijenjeni i stvarni poredak akcija.
- `q08_failure_analysis.json` sadrži objedinjenu dijagnozu i doprinos greške ukupnom propuštenom dobitku faze B.
- `query-index.csv` i `manifest.json` povezuju javne SQL datoteke s izvornim putanjama, commitom i SHA-256 vrijednostima.

Katalog služi provjeri jedne zadržane greške sekundarne memorijske analize. Ne predstavlja novi reprezentativni korisnički slučaj niti glavni izlaz rada.
