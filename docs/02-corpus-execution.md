# Corpus, SQL instance i izvršavanje

## Terminologija

- **Template** je parametrizovani SQL obrazac.
- **Instanca** je konkretno renderovani SQL.
- **Uslov** povezuje SQL, dataset, runtime, topologiju i intervencijsku ulogu.
- **Izvršni slot** je jedno planirano ponavljanje uslova.
- **Attempt** je fizičko pokretanje ili nastavak prekinutog programa.
- **Logical run** bira kanonski uspješan attempt bez brisanja historije.

Za naučni argument važni su izvršenje, rekonstruisano stanje, deklarisana intervencija i izmjeren ishod. Niži nivoi postoje radi sigurnog nastavka i audita collectora.

## Tri toka dokaza

| Tok | Ključni corpusi | Uloga |
| --- | --- | --- |
| Karakterizacija | `clean-run-v1`, companion i STATS-CEB | `F19`, RQ1-RQ4 i vanjske projekcije; `F21-dev` ostaje razvojna ablacija |
| Intervencije i paneli | `pressure-raw-v1`, DBA, N2/N3 i confirmatory | prije/poslije dokaz, ablation i granice prenosa |
| Longitudinalne putanje | `feedback-loop-v1` i aggregate-exact | odluka, tranzicija, rollback i replay |

`reproducibility/query-catalog.csv` je autoritativna navigacija kroz svaki upakovani SQL. Broj SQL fajlova nije uvijek jednak broju izvršenja: ista SQL instanca može biti ponovljena ili izvršena pod više konfiguracijskih uslova.

## Glavni dizajni

| Blok | SQL fajlovi/uslovi | Izvršenja |
| --- | --: | --: |
| Široki intervencijski program | 799 jedinstvenih SQL fajlova, 869 uslova | 2.607 |
| Završni DBA panel | 60 SQL uslova | 180 |
| Kontrolisani N2/N3 panel | 180 SQL instanci | 180 |
| Potvrdni panel | 60 uslova | 300 |
| Feedback-loop aggregate exact replay | 5 stanja u Williams rasporedu | 25 |

Široki program sadrži 418 kontrolisanih prije/poslije parova. Završni DBA panel koristi 15 SQL oblika, tri pojavljivanja i tri poznate akcije. Potvrdni panel koristi novih 15 SQL oblika, baseline i tri akcije, uz pet balansiranih ponavljanja svakog uslova.

## Dataset i vremenski ugovor

Svaka novija SQL instanca vezana je za `dataset_profile_id`. Profil definise generator, sjeme, regionalne raspone, shardove i `base_time_unix`. Glavni noviji profili koriste oslonac `1782864000`, odnosno `2026-07-01T00:00:00Z`.

Pojedini template zadržava fallback `now()` radi interaktivne upotrebe. U izmjerenom SQL-u glavni programi prosljeđuju nenulti `as_of_unix`, pa se fallback ne izvršava. Temporalni status svakog bloka nalazi se u `releases/temporal-validity-audit-v1/`.

## Lokalna provjera generic corpusa

```bash
make corpus-list
make corpus-validate CORPUS=clean-run-v1
make corpus-render CORPUS=clean-run-v1
make corpus-stage
make corpus-dry-run CORPUS=clean-run-v1
```

`config/corpora.json` sadrži generičke corpuse koje standalone workflow može direktno stageovati. Noviji zaključani paneli imaju posebne validacijske konfiguracije u `sources/master-regimes/configs/validation/` i njihove autoritative renderovane SQL fajlove u `artifacts/rendered-corpora/`.

## Stvarno izvršavanje

Generic putanja je:

```bash
make corpus-run CORPUS=clean-run-v1
make corpus-index CORPUS=clean-run-v1
make feature-matrix CORPUS=clean-run-v1
```

Runner za svaki segment učitava odgovarajući dataset, primjenjuje runtime i mrežni profil, obnavlja FDW/ETL strukture, izvršava SQL, prikuplja GAC, regionalni i worker/task dokaz te zapisuje status poslije svakog slota. Rezultatni redovi se ne čuvaju; jednakost se provjerava ordered ili multiset hashom prema ugovoru upita.

## Prekid i nastavak

```bash
make corpus-index CORPUS=clean-run-v1
make corpus-rerun-plan CORPUS=clean-run-v1
```

Novi attempt ne prepisuje prethodni. Logical index bira valjan rezultat za svaki `execution_slot_id`, a sve pokušaje zadržava za audit.

## Mrežne intervencije

Mrežni uslovi su kontrolisano emulirani pomoću `tc/netem` u fizički kolociranom VPC-u. Apply i reset manifest moraju proći prije prihvatanja tranzicije. Ovi rezultati ne predstavljaju mjerenje prirodne Amsterdam-US ili Amsterdam-APAC cloud putanje.

## STATS-CEB

STATS-CEB je vanjski schema/workload audit, a ne dataset glavnih intervencijskih panela. Svih 146 upita ostaje u planu bez selekcije prema ishodu. Potpuni collector i no-refit projekcija postoje za 130 upita; timeouti ostaju u statusnom tragu.
