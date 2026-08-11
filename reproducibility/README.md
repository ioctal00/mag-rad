# Navigacija kroz ulaze za provjeru i ponovno izvođenje

Ovaj direktorij povezuje SQL, sintetičke skupove podataka, izvorni kod i rezultate koje rad koristi. Čitalac ne mora pogađati interni naziv runa niti pretraživati repozitorij po oznakama `q05`, `q08` ili `CASE-*`.

Za brzi ljudski pregled koristiti top-level direktorije:

- [`queries/`](../queries/) za `q01`-`q30`, njihove N2/N3 instance i šablone;
- [`datasets/`](../datasets/) za stvarno korištene profile;
- [`corpora/`](../corpora/) za vezu između SQL ulaza i rezultata.

## Najkraći put

1. `query-catalog.csv` navodi svaki upakovani renderovani SQL, njegov SHA-256, eksperimentalni blok, dataset, topologiju, intervenciju i parametre.
2. `dataset-catalog.csv` povezuje svaki `dataset_profile_id` sa verzionisanim YAML profilom, generatorom, sjemenom i vremenskim osloncem.
3. `evidence-blocks.json` opisuje dizajn glavnih eksperimenata i pokazuje gdje su njihovi rezultati.
4. `source-provenance.csv` bilježi commit svakog kuriranog izvornog snapshot-a.
5. `query-coverage.csv` otvoreno navodi gdje je sačuvan potpuni SQL, gdje se SQL ponovo koristi iz drugog corpusa i gdje su ostali historijski fajlovi koji nisu dio autoritativnog eksperimentalnog manifesta.
6. `audits/REPRODUCIBILITY_AUDIT.md` konsoliduje Terraform, Ansible, dataset, sweep i collector audit. Svaka oblast ima vlastiti offline validator i JSON nalaz u odgovarajućem poddirektoriju.

Katalog se ponovo gradi komandom:

```bash
make reproducibility-catalog
```

Provjera svih veza i hash vrijednosti ne pokreće SQL:

```bash
make reproducibility-check
```

Potpuni offline audit svih slojeva pokreće se bez pristupa infrastrukturi:

```bash
make reproducibility-audit
```

Varijanta `make reproducibility-audit-full` dodatno ponovo računa svaki hash iz release manifesta.

Audit privatnosti i prenosivosti trenutnog javnog stabla pokreće se sa:

```bash
make public-check
make public-audit-full
```

Druga komanda uključuje kompresovane arhive i pregled Git historije. Runtime IP adrese i lokalne home putanje uklonjene su iz trenutnog release stabla; logički nazivi čvorova, planovi i mjerne vrijednosti ostaju sačuvani.

## Glavni eksperimentalni blokovi

| Blok | SQL ulaz | Dataset ugovor | Rezultat |
| --- | --- | --- | --- |
| Široki intervencijski korpus | `artifacts/rendered-corpora/pressure-raw-v1/` | profili iz `dataset-catalog.csv`; 869 uslova, tri ponavljanja | `artifacts/results/pressure-actionability-v1/` |
| Završni DBA panel | `artifacts/rendered-corpora/dba-local-memory-v1/` | N2/N3 i raw profili | `releases/consolidated-evaluation-v1/` |
| Kontrolisani topology-memory panel | `artifacts/rendered-corpora/n3-topology-memory-v1/` | upareni `topology-isolation-*-n2/n3` profili | `releases/consolidated-evaluation-v1/` |
| Potvrdni panel | `artifacts/rendered-corpora/confirmatory-action-replication-v1/` | `topology-isolation-large-n3-v1` | `releases/confirmatory-action-replication-v1/` |
| Longitudinalni feedback loop | `artifacts/rendered-corpora/feedback-loop-v1/` | zamrznuti lokalni snapshot i vremenski ugovor | `releases/feedback-loop-execution-v1/` i `releases/feedback-loop-analysis-v1/` |
| F19 karakterizacija i historijska F21-dev ablacija | `artifacts/rendered-corpora/clean-run-v1/` i prateći corpusi | profili navedeni u katalogu | `releases/rq-alignment-v2/` i `releases/fcm-f21-development-v1/` |

## Šta znači da je dataset uključen

Paket ne distribuira dump višemilionskih PostgreSQL tabela. Skupovi su sintetički i uključeni su kao ponovljiv ugovor:

```text
DDL i loader
+ dataset profil
+ commit generatora
+ sjeme
+ base_time_unix
+ regionalni rasponi i shard ugovor
```

Implementacija generatora je u `sources/citus-datagen/`, profili su u `sources/master-regimes/datasets/profiles/`, a primjena profila i bootstrap topologije u `sources/master-regimes-infra/`. Glavni noviji profili koriste `base_time_unix=1782864000` (`2026-07-01T00:00:00Z`), tako da statični datumi u SQL-u označavaju odmak od skupa podataka, a ne datum pokretanja eksperimenta.

Materijalizovani row-level checksum cijelog dataseta nije sačuvan. Zato paket garantuje determinističku konstrukciju podataka pod navedenim commitom i profilom, ali ne tvrdi da je izvršen nezavisan bit-po-bit audit svake ponovo učitane tabele. Longitudinalni feedback loop dodatno koristi identitet `locked_current_dataset_snapshot`: stvarni brojevi redova i raspored su auditovani tokom runa, ali izvorni naziv profila nije zabilježen. Ta putanja je reproduktivna na nivou SQL-a, protokola i objavljenih rezultata, ne kao potpuno garantovan novi dataset reload.

## Historijski SQL izuzeci

`pressure-raw-v1` sadrži i 80 starijih rendera iz razvoja skew segmenta. Oni nisu povezani sa završnom matricom od 869 uslova i zato nisu u `query-catalog.csv`; ostavljeni su radi audita historije. Katalog obuhvata 799 jedinstvenih SQL fajlova koje autoritativni manifest stvarno referencira.

Kod `confirmatory-skew-v1` originalni render direktorij nije sačuvao SQL uz manifest. Svih 48 stvarno izvršenih `input/query.sql` fajlova zato je deterministički izdvojeno iz objavljene raw arhive u `artifacts/rendered-corpora/confirmatory-skew-v1/queries/`.

`repeatability-v1` ponovo koristi SQL iz već upakovanih corpusa, pa nema zaseban direktorij SQL kopija. Stvarna putanja ponovo korištenog fajla nalazi se u katalogu.

## Nivoi reprodukcije

- **Integritet paketa:** SHA-256 potvrđuje da objavljeni fajl nije promijenjen.
- **Offline analiza:** objavljeni CSV/JSON rezultati i zamrznuti ugovori mogu se ponovo provjeriti bez baze.
- **Dataset regeneracija:** zahtijeva generator, profil, sjeme i vremenski oslonac iz kataloga.
- **Infrastrukturni rerun:** zahtijeva VPS resurse i može dati druga apsolutna vremena zbog planera, cachea, virtualizacije i mrežnog suma.

SQL rezultatni redovi i database dumpovi nisu objavljeni. Sačuvani su rezultatski hash ugovori, planovi, mjerenja i sažeci potrebni za provjeru jednakosti i zaključaka rada.
