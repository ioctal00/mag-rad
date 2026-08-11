# Reprezentativni slučajevi

Ovaj direktorij je čitljivi ulaz u eksperimentalne artefakte rada. PDF objašnjava analitičku namjeru i glavni nalaz; ovdje su dostupni puni SQL, stvarni planski artefakti, medijane pokazatelja i porijeklo izvora.

Svi kurirani slučajevi koriste zamrznuti vremenski oslonac skupa podataka. Kalendarski literali u SQL-u predstavljaju verzionisane relativne presjeke, ne vrijeme pokretanja komande. Svaki `manifest.json` navodi oslonac, prozor generatora i odmake konkretnih upita.

Tri slučaja odgovaraju trima operativnim tokovima:

1. ponavljanje istog SQL-a;
2. isti SQL nakon deklarisane konfiguracijske intervencije;
3. različite SQL varijante iste ručno povezane analitičke namjere.

`CASE-AGG-01` i `CASE-WAN-01` predstavljaju dva javna presjeka iste tačne agregacijske putanje koja vodi metodološki narativ rada: početno i vraćeno stanje te WAN tranziciju nakon regionalne redukcije. `CASE-JOIN-01` je komplementarna planska dubinska studija SQL preoblikovanja.

Počnite od [indeksa slučajeva](case-index.md). Kompletan generisani korpus ostaje u `artifacts/rendered-corpora/`; nije potreban za razumijevanje ova tri primjera.

Direktorij [`Q08-NEIGHBORS`](Q08-NEIGHBORS/) zasebno čuva šest tačno izvršenih SQL iskaza i puni trag najveće greške sekundarne cross-query procjene. On je auditni katalog, a ne četvrti reprezentativni slučaj.

Direktorij [`PLAN-SOURCE-01`](PLAN-SOURCE-01/) cuva sanitizovane JSON planove iza PEV2 prikaza iz rukopisa. To su dva nezavisna ilustrativna plana, ne povezani slojevi istog izvršenja niti ulaz u numeričke rezultate.

## Reprodukcija paketa

```bash
make examples
make examples-check
```

Generator čita samo postojeće artefakte. Ne pokreće SQL niti mijenja infrastrukturu.
