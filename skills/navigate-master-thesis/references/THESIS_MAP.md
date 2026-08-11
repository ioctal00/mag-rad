# Karta rada i javnih artefakata

## 1. Korijeni i autoritet

`PACKAGE_ROOT` je korijen repozitorija `master-thesis-final`.

| Sloj | Uloga | Autoritativni ulaz |
| --- | --- | --- |
| Rukopis | naučni narativ, RQ/H, tabele i zaključci | sibling `master-regimes-thesis/manuscript/`, kada je dostupan |
| Javni paket | kurirani dokazi i reprodukcija | `PACKAGE_ROOT/START_HERE.md` |
| Veza tvrdnje i dokaza | provjera šta podržava centralnu tvrdnju | `artifacts/claim-evidence-map.json` |
| Eksperimentalni dizajn | broj izvršenja, uslova i odluka | `reproducibility/evidence-blocks.json` |
| Izvorni kod | collector, analize, infra i generator | `sources/` |
| Integritet paketa | SHA-256 i source commitovi | `artifacts/release-manifest.json`, `reproducibility/source-provenance.csv` |

Rukopis objašnjava zašto je nešto korišteno. Release i mašinski artefakti potvrđuju broj ili rezultat. Izvorni kod pokazuje implementaciju, ali sam po sebi nije dokaz eksperimentalnog ishoda.

## 2. Poenta rada

Osnovni tok je:

```text
SQL izvršenje
-> višeslojna rekonstrukcija GAC/FDW/Citus/worker dokaza
-> fizičko stanje
-> deklarisana DBA intervencija
-> ponovljeno izvršenje i provjera rezultata
-> fizičke razlike, trajanje i trajni lokalni zapis
```

Sistem prvenstveno evidentira i objašnjava izmjeren ishod intervencije. Ne predstavlja univerzalni optimizer. Korisnik može ručno povezati različite SQL varijante istim `logical_question_id`, ali sistem time ne dokazuje opću semantičku ekvivalentnost SQL-a.

## 3. Četiri numerička pogleda

| Oznaka | Značenje | Glavna lokacija | Ne znači |
| --- | --- | --- | --- |
| `R6` | relativna promjena šest domena između povezanih stanja | `releases/feedback-loop-analysis-v1/`, `experiments/feedback-loop-v1/` | procenat uzroka ili doprinos trajanju |
| `F19` | završni FCM pogled sa 19 pokazatelja za RQ1-RQ4 | `releases/rq-alignment-v2/`, `artifacts/results/semantic-v2-model-freeze/` | akcijski optimizer |
| `F21-dev` | raniji razvojni FCM pogled sa 21 pokazateljem | `releases/fcm-f21-development-v1/` | završni model rada |
| `P64->6` | PCA prostor 64 aktivna pokazatelja u šest komponenti za sekundarnu pretragu | `analysis/reports/fuzzy-intervention-memory-v1/`, `configs/models/fuzzy_intervention_memory_v1.yml` | isto što i šest fizičkih domena `R6` |

Provjeru da se ovi modeli ne miješaju daje `releases/model-lineage-audit-v1/`.

## 4. Brza navigacija

| Korisnik traži | Prvo otvoriti | Zatim provjeriti |
| --- | --- | --- |
| `q01` do `q30` | `queries/thesis-query-index.csv` | `queries/instances/` i puni naziv corpusa |
| bilo koji renderovani SQL | `reproducibility/query-catalog.csv` | `artifacts/rendered-corpora/<corpus>/` |
| SQL template | `queries/template-index.csv` | `sources/master-regimes/workloads/templates/` |
| `logical_question_id` ili SQL identitet | `releases/consolidated-evaluation-v1/sql_identity_audit.csv` | odgovarajući manifest corpusa |
| dataset, seed ili vremenski oslonac | `datasets/dataset-index.csv` | `sources/master-regimes/datasets/profiles/` |
| DDL i Citus raspodjelu | `sources/citus-datagen/sql/minimal_schema.sql` | `sources/citus-datagen/diagrams/current-schema-erd.svg` |
| corpus i njegovu ulogu | `corpora/corpus-index.csv` | `reproducibility/evidence-blocks.json` |
| stvarni SQL, plan i metrike primjera | `examples/` | manifest i checksum unutar slučaja |
| planske JSON artefakte iz rada | `examples/PLAN-SOURCE-01/` | odgovarajući `CASE-*` primjer |
| F19 prototipe i RQ1-RQ4 | `releases/rq-alignment-v2/` | `artifacts/results/semantic-v2-final-consistency/` |
| široki intervencijski korpus | `artifacts/results/pressure-actionability-v1/` | `analysis/reports/pressure-raw-v1-mitigation-action-audit/` |
| R6 putanje, rollback ili replay | `releases/feedback-loop-execution-v1/` | `releases/feedback-loop-analysis-v1/` |
| ispravku šeste R6 domene | `releases/feedback-loop-r6-correction-v1/` | `docs/05-feedback-loop-r6-correction.md` |
| završni DBA ili N2/N3 panel | `releases/consolidated-evaluation-v1/` | `dataset_provenance.csv`, `coverage_regret_curve.csv` |
| potvrdni panel novih SQL oblika | `releases/confirmatory-action-replication-v1/` | `evaluation_summary.csv`, `per_scenario_predictions.csv` |
| zašto je 300 izvršenja samo 15 odluka | `releases/action-selection-sample-size-audit-v1/` | `experimental_units.csv`, `confirmatory_top1_uncertainty.csv` |
| veličinu memorije i susjedstva | `releases/retrieval-density-geometry-audit-v1/` | `prior_panel_memory_comparison.csv` |
| representation ablation | `releases/representation-ablation-e1-e4-v1/` | `representation_summary.csv`, `leakage_audit.json` |
| `q08` failure case | `examples/Q08-NEIGHBORS/` | susjedi i stvarni pobjednici u manifestu |
| temporalnu ponovljivost | `releases/temporal-validity-audit-v1/` | `datasets/dataset-index.csv` |
| Terraform i Ansible | `sources/master-regimes-infra/` | `reproducibility/audits/` |
| puni status reproducibilnosti | `reproducibility/audits/REPRODUCIBILITY_AUDIT.md` | `reproducibility/audits/summary.json` |

## 5. Eksperimentalni blokovi i dozvoljeni zaključci

| Blok | Jedinice | Primarna uloga | Ne koristiti za |
| --- | --- | --- | --- |
| F19 karakterizacijski korpus | 1.964 rekonstruisana stanja | opis FCM prototipa i RQ1-RQ4 | Top-1 evaluaciju akcija |
| Široki intervencijski korpus | 2.607 izvršenja, 869 uslova, 418 parova | collector, provjera rezultata i fizički odziv više porodica intervencija | najbolju od tri akcije nad istim stanjem |
| Razvojni/reference panel | 312 izvršenja, 26 stanja | razvoj `P64->6`, `k`, udaljenosti, P99 i komparatora | finalni holdout |
| Završni DBA panel | 180 izvršenja, 45 odluka, 15 SQL oblika | vremenski uređena direktna i cross-query memorija | 45 nezavisnih novih SQL oblika |
| Kontrolisani topology panel | 180 izvršenja, 45 stanja, 15 SQL oblika | N2/N3 fizički pomak i lokalna adaptacija | opću promjenu najbolje akcije zbog topologije |
| Potvrdni panel | 300 izvršenja, 15 novih SQL oblika, pet ponavljanja uslova | stabilni stvarni pobjednici i ograničeni test prijenosa | 300 nezavisnih Top-1 primjera |
| Longitudinalni feedback loop | 85 redova glavnog manifesta i 25 aggregate-exact replay izvršenja | R6 tranzicije, unaprijed zapisana odluka, rollback i ponovljivost | optimalnost sekvence intervencija |

U potvrdnom panelu prequential politika izdaje 14 preporuka i tačno bira 8 pobjednika. To je `8/14`, ne `8/15` i ne rezultat nad 300 nezavisnih odluka.

## 6. SQL identiteti

Razlikuj:

1. isti normalizovani SQL;
2. isti SQL prije i poslije deklarisane intervencije;
3. različite SQL varijante koje je korisnik povezao istim `logical_question_id`;
4. fizički bliska stanja u `P64->6`, koja nisu semantički identitet.

Kratka oznaka nije dovoljna. Na primjer, `q07_tenant_count` iz završnog/N3 panela nije historijski `q07_global_user_segment_join` iz karakterizacijskog corpusa.

## 7. Porijeklo brojeva

Za numeričko pitanje koristi ovaj redoslijed:

1. specifični release CSV/JSON;
2. `artifacts/claim-evidence-map.json`;
3. `reproducibility/evidence-blocks.json` za nazivnike;
4. rukopis za tumačenje;
5. README samo kao navigaciju.

Ako se broj izvršenja, stanja, odluka i SQL oblika razlikuje, to obično nisu kontradiktorni brojevi nego različite jedinice. Objasni svaku jedinicu prije zaključka.

## 8. Oznake dodatnih artefakata

Rukopis koristi oznake `S1` do `S6`. Njihova aktuelna mapa nalazi se u `README.md`, u tabeli "Oznake dodatnih artefakata iz rukopisa". Ne nagađaj značenje oznake iz samog broja.
