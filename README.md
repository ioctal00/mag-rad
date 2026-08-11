# Paket za provjeru i ponovno izvođenje magistarskog rada

Ovaj repozitorij sadrži implementaciju i artefakte za provjeru i ponovno izvođenje sistema za višeslojnu rekonstrukciju geo-distribuiranog PostgreSQL/Citus izvršenja, neizrazitu karakterizaciju fizičkih režima i longitudinalnu analizu deklarisanih DBA intervencija. Fokus je na izlazima eksperimenata i minimalnom izvršnom kodu potrebnom da se oni ponovo proizvedu. Rukopis, LaTeX izvori i PDF kopije nisu dio paketa.

Sistem ne pretpostavlja da unaprijed poznaje sve PostgreSQL/Citus promjene. On povezuje izvršenje prije i poslije deklarisane intervencije, provjerava rezultat i prikazuje kako su se promijenili plan, tok podataka, raspodjela rada, resursi i end-to-end trajanje. Automatsko rangiranje poznatih akcija je sekundarna evaluirana ekstenzija, a ne završni proizvod rada.

## Počnite ovdje

Najkraća navigacija je u [`START_HERE.md`](START_HERE.md). Direktni ulazi su:

- [`queries/`](queries/) za `q01`-`q30`, SQL šablone i tačne instance;
- [`datasets/`](datasets/) za stvarno korištene dataset profile;
- [`corpora/`](corpora/) za vezu corpusa, SQL ulaza i rezultata;
- [`examples/`](examples/) za nekoliko čitljivih prije/poslije slučajeva.

Za potpunu navigaciju kroz SQL, dataset profile, izvorne commitove i rezultate otvoriti [`reproducibility/`](reproducibility/). Katalog sadrži 3.819 tačnih renderovanih SQL fajlova iz 14 corpusa i 29 dataset ugovora. Svaki red navodi SHA-256, eksperimentalnu ulogu, parametre, topologiju i pripadajući dataset.

Za razumijevanje rada nije potrebno pregledati cijeli generisani korpus. Direktorij [`examples/`](examples/) sadrži tri kurirana slučaja sa punim SQL-om, stvarnim planskim artefaktima, medijanama mjerenja i provjerljivim porijeklom:

1. [`CASE-AGG-01`](examples/CASE-AGG-01/) - početak i završni povrat vođene tačne agregacijske putanje;
2. [`CASE-WAN-01`](examples/CASE-WAN-01/) - WAN tranzicija iste putanje nakon regionalne redukcije;
3. [`CASE-JOIN-01`](examples/CASE-JOIN-01/) - komplementarna planska dubinska studija dvije SQL varijante iste analitičke namjere.

Za analizu najveće greške sekundarne memorije, katalog [`Q08-NEIGHBORS`](examples/Q08-NEIGHBORS/) čuva ciljni upit, svih pet susjednih SQL upita i potpuni trag njihove procjene. Katalog je odvojen od tri reprezentativna korisnička slučaja.

Izvorni JSON planovi iza dva PEV2 prikaza iz rukopisa dostupni su u [`PLAN-SOURCE-01`](examples/PLAN-SOURCE-01/). To su dva nezavisna ilustrativna plana, ne povezani slojevi istog izvršenja niti ulaz u numeričke rezultate.

Prva dva slučaja čitaju se zajedno kao longitudinalni korisnički tok. Treći pokazuje šta jedna složena SQL tranzicija mijenja u GAC i regionalnim planovima.

## Oznake dodatnih artefakata iz rukopisa

Rukopis koristi kratke oznake `S1`-`S6` kako naučni tekst ne bi prekidao internim putanjama. Ova tabela je početna navigacija prema njihovim stvarnim lokacijama u paketu:

| Oznaka | Sadržaj | Lokacija |
| --- | --- | --- |
| `S1` | Audit dostupnosti, varijabilnosti i odabira 93 kandidatska pokazatelja | [`feature_selection_audit.csv`](analysis/reports/fuzzy-intervention-memory-v1/feature_selection_audit.csv) |
| `S2` | Zamrznuti ugovor transformacije sekundarnog prostora `P64->6` | [`fuzzy_intervention_memory_v1.yml`](configs/models/fuzzy_intervention_memory_v1.yml) |
| `S3` | Autoritativni `F19` audit za RQ1-RQ4, prototipi i doprinosi pokazatelja | [`releases/rq-alignment-v2/`](releases/rq-alignment-v2/) |
| `S4` | Protokol i rezultati longitudinalnih tranzicija te potvrdne i sekundarne evaluacije | [`experiments/feedback-loop-v1/`](experiments/feedback-loop-v1/), [`releases/feedback-loop-execution-v1/`](releases/feedback-loop-execution-v1/), [`releases/feedback-loop-analysis-v1/`](releases/feedback-loop-analysis-v1/), [ispravka šeste R6 domene](docs/05-feedback-loop-r6-correction.md), [`releases/`](releases/), [`analysis/reports/`](analysis/reports/) |
| `S5` | Puni SQL, planovi i mjerenja reprezentativnih studija slučaja | [`examples/`](examples/) |
| `S6` | Naknadni auditi jedinica procjene, veličine memorije, susjedstva i action-response geometrije | [`releases/action-selection-sample-size-audit-v1/`](releases/action-selection-sample-size-audit-v1/), [`releases/retrieval-density-geometry-audit-v1/`](releases/retrieval-density-geometry-audit-v1/) |

SHA-256 vrijednosti svih objavljenih fajlova nalaze se u [`artifacts/release-manifest.json`](artifacts/release-manifest.json). Taj manifest treba ponovo generisati pri svakom označenom izdanju paketa.

## Replay-first demonstrator

Podrazumijevani demonstrator ne pokreće infrastrukturu. Čita već provjerene SQL-ove, planove, mjerne sažetke i manifeste ovim redom:

1. `CASE-AGG-01` prikazuje početno i vraćeno stanje iste analitičke namjere;
2. `CASE-WAN-01` prikazuje jednu fizičku tranziciju između tih stanja;
3. `CASE-JOIN-01` prikazuje kako SQL preoblikovanje iste ručno deklarisane namjere mijenja više slojeva plana i toka podataka.

Komande `make examples-check` i `make verify` provjeravaju taj prikaz bez SQL izvršenja. Živo ponovno izvršavanje je zasebna, opciona putanja opisana u odjeljku `Potpuno ponovno izvršavanje`; nije potrebno za pregled rezultata.

## Vremenski ugovor skupa podataka

Glavni eksperimentalni profili ne generišu vremenske oznake prema datumu pokretanja. Koriste zamrznuti oslonac `base_time_unix=1782864000`, odnosno `2026-07-01T00:00:00Z`, verzionisano sjeme i prozor generatora od 30 dana. Datumi kao `2026-06-01` u renderovanom SQL-u predstavljaju relativne odmake od tog oslonca. Ponovno izvođenje zato mora koristiti pripadajući dataset profil i njegov manifest, a ne samo ponovo izvršiti SQL nad proizvoljno regenerisanim podacima. Kurirani `manifest.json` fajlovi navode oslonac i odmake upita.

## Šta je uključeno

| Putanja | Sadržaj |
| --- | --- |
| `sources/master-regimes-infra/` | Terraform, Ansible, collector, indexer i corpus runner |
| `sources/master-regimes/` | corpus renderer, parser, feature extractor i semantic-V2 kod |
| `sources/citus-datagen/` | generator i loader sintetičkih podataka |
| `sources/psql-benchmarks/` | SQL capture, `EXPLAIN` i FDW/ETL alati |
| `reproducibility/` | Jedinstveni katalog SQL-a, dataset profila, dokaznih blokova i source commitova |
| `reproducibility/audits/` | Offline Terraform, Ansible, dataset, sweep i collector validatori sa konsolidovanim nalazom |
| `examples/` | Tri reprezentativna slučaja, q08 audit i izvorni planovi planske ilustracije |
| `artifacts/rendered-corpora/` | Tačno renderovani SQL-ovi, parametri i planovi izvršavanja corpusa, uključujući glavne završne panele |
| `artifacts/raw-attempts/` | kompresovani planovi, logovi i run manifesti |
| `artifacts/logical-indexes/` | kanonski logical-run indeksi |
| `artifacts/features/` | feature matrice korištene u završnoj analizi |
| `artifacts/results/` | mašinski čitljivi rezultati i zamrznuti model |
| `releases/feedback-loop-r6-correction-v1/` | offline audit i korigovani prikaz reparticionisanja i lokalnosti u longitudinalnom R6 profilu |
| `artifacts/results/pressure-actionability-v1/` | 418 intervencijskih parova, colocation rangiranje i N=3 no-refit dokaz |
| `artifacts/publication/` | pregledivi SVG/PNG prikazi i njihovi CSV/JSON izvori |
| `artifacts/claim-evidence-map.json` | veza centralnih tvrdnji sa provjerljivim izlazima |
| `analysis/reports/` | kurirani izvještaji i pojedinačni zapisi obuhvaćeni oznakama `S1` i `S4` |
| `experiments/feedback-loop-v1/` | zamrznuti longitudinalni protokol, ugovori i dry-run provjere iz `S4` |
| `releases/` | Autoritativni `F19`, historijski `F21-dev`, longitudinalni, representation-ablation, konsolidovani, temporalni i potvrdni rezultati |
| `configs/` | javni ugovori pokazatelja i transformacija, uključujući `S2` |
| `skills/navigate-master-thesis/` | LLM postupak i karta za pronalazak, provjeru i objašnjenje artefakata rada |

Smoke/probe runovi, napušteni modelski pravci, `llmcontext`, notebooki i necitirani razvojni izvještaji nisu uključeni. Sačuvan je samo podskup narativnih i mašinski čitljivih izlaza na koje rukopis neposredno upućuje. Ostala dokumentacija iz izvornih repozitorija je uklonjena, a njihovi `README.md` fajlovi svedeni su na package metadata koji zahtijeva Python build. Materijalizovani database dumpovi i rezultatski redovi SQL upita nisu pohranjeni. Sintetički dataset je uključen kao generator, DDL, loader, verzionisani profil, sjeme i vremenski oslonac. Raw arhive sadrže planove, bindinge, timing i audit metapodatke.

## Brza lokalna provjera

Za provjeru integriteta nisu potrebni cloud resursi:

```bash
make verify
make public-check
make reproducibility-audit
make reproducibility-catalog
make reproducibility-check
make examples-check
make source-test
make extract-indexes
make feature-matrix CORPUS=clean-run-v1
make semantic-rebuild
make semantic-compare
```

`make semantic-compare` mora potvrditi da ponovo izgrađena matrica i model odgovaraju zamrznutim SHA-256 vrijednostima.

`make reproducibility-catalog` je deterministički build korak. Ponovo izdvaja 48 historijskih confirmatory-skew SQL fajlova iz objavljene raw arhive i gradi CSV/JSON navigaciju. `make reproducibility-check` zatim provjerava svaki SQL i dataset hash, vremenski ugovor glavnih corpusa, source commitove i prisustvo svih autoritativnih rezultata.

`make reproducibility-audit` ne pristupa infrastrukturi. Ponovo provjerava deklarativnu topologiju, konfiguracijske ugovore, stvarno korištenje dataset profila, broj i redoslijed sweep slotova te veze između GAC, regionalnih i worker/task artefakata. Nalaz otvoreno razlikuje ono što paket može ponoviti od historijskih i runtime ulaza koji nisu sačuvani.

`make source-test` pokreće kurirani testni skup za objavljene eksperimentalne skripte, infrastrukturne ugovore, generator podataka i OS sampler. Historijski testovi za razvojne skripte koje nisu dio ovog paketa namjerno nisu uključeni.

## Potpuno ponovno izvršavanje

Cloud izvršavanje troši novac. Prvo pročitati [`docs/01-infrastructure.md`](docs/01-infrastructure.md) i podesiti tajne preko lokalnog environment fajla koji nije dio repozitorija.

```bash
make infra-env
make infra-up
make corpus-list
make corpus-validate CORPUS=clean-run-v1
make corpus-render CORPUS=clean-run-v1
make corpus-dry-run CORPUS=clean-run-v1
make corpus-run CORPUS=clean-run-v1
make corpus-index CORPUS=clean-run-v1
make infra-down
```

Runner ponovo učitava odgovarajući dataset i izvršava FDW/ETL bootstrap po segmentu. Prekid ne briše uspješne artefakte; novi attempt se spaja preko logical-run indeksa.

## Dokumentacija

1. [Obim paketa](docs/00-scope.md)
2. [Infrastruktura](docs/01-infrastructure.md)
3. [Corpus i izvršavanje](docs/02-corpus-execution.md)
4. [Offline analiza](docs/03-offline-analysis.md)
5. [Mapa artefakata](docs/04-artifact-map.md)
6. [Provenance i granice](docs/05-provenance-and-limits.md)
7. [SQL i dataset navigacija](reproducibility/README.md)
8. [Konsolidovani audit ponovljivosti](reproducibility/audits/REPRODUCIBILITY_AUDIT.md)

## Završni istraživački ugovor

Primarni ugovor rada je:

```text
deklarisano povezana izvršenja
-> dva višeslojna traga
-> provjera rezultatske uporedivosti
-> relativna promjena plana, fizičkih pokazatelja, resursa i trajanja
-> lokalni zapis intervencije
```

Normalizovani pokazatelji organizovani su u šest domena fizičkog dokaza. Njihove vrijednosti tumače se relativno prema početnom i prethodnom lokalnom stanju, bez univerzalnih granica "visokog" i "niskog" pritiska. Jedna intervencija može istovremeno promijeniti više domena, pa domenske vrijednosti nisu procenti uzroka niti direktni doprinosi ukupnom trajanju.

Autoritativni FCM pogled `F19` koristi 19 semantički transformisanih i porodično ponderisanih pokazatelja. Njegov ugovor, zamrznuti centri, članstva i provjere nalaze se u `artifacts/results/semantic-v2-*`. Raniji `F21-dev` sa 21 standardizovanim pokazateljem ostaje razvojna ablacija i nije osnova završnih odgovora na RQ1-RQ4. FCM centri ostaju uslovljeni karakterizacijskim korpusom. FCM opisuje kompozitna i mješovita stanja, ali članstva nisu udjeli fizičkih pritisaka, procjene uzroka ni očekivana ubrzanja.

Treća reprezentacija, `P64->6`, potpuno je odvojeni PCA prostor za sekundarnu kNN pretragu i poređenje prototipske memorije. Njegov FCM komparator nije model `F19` niti `F21`. Mašinski audit ove podjele nalazi se u `releases/model-lineage-audit-v1/`.

Ridge colocation model, kNN memorija, K-means/FCM kompresija memorije i N=3 provjere ostaju objavljeni kao sekundarne analize. Potvrdni panel novih SQL oblika nije podržao robustan univerzalni cross-query prijenos, pa nijedan od tih modela nije predstavljen kao opći PostgreSQL optimizer.

Puni vanjski FCM audit pokušava svih 146 STATS-CEB upita bez odabira prema ishodu. Poređenje rezultata završeno je za 132 upita bez pronađenog neslaganja, a 130 upita ima potpun collector, feature i no-refit projection izlaz. Timeouti ostaju u objavljenom statusnom tragu.
