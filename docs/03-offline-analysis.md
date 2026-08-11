# Offline analiza

## 1. Provjera ulaza

```bash
make reproducibility-catalog
make reproducibility-check
```

Prva komanda gradi katalog svih renderovanih SQL fajlova, dataset profila, source commitova i eksperimentalnih blokova. Druga provjerava SQL/profile hash, temporalni ugovor glavnih corpusa i prisustvo svih rezultata.

## 2. Longitudinalni zapis

Izvršni dokaz je u:

```text
releases/feedback-loop-execution-v1/
```

Najvažniji fajlovi su:

- `decision_log.jsonl`: hipoteza zapisana prije ishoda;
- `execution_manifest.csv`: stvarno izvršeni slotovi;
- `trajectory_states.csv` i `trajectory_transitions.csv`: putanja stanja;
- `raw_signal_deltas.csv` i `domain_profile_deltas.csv`: fizička promjena;
- `result_equivalence_audit.csv`: provjera rezultata;
- `rollback_audit.csv`: povrat konfiguracije.

Analitički sažetak, stabilnost, heatmape i lokalni replay nalaze se u `releases/feedback-loop-analysis-v1/`. Taj direktorij čuva izvorni izvedeni release. Naknadno je utvrđeno da je tekstualna vrijednost `false` indikatora reparticionisanja bila izgubljena pri numeričkoj konverziji. Obrazloženje je u `docs/05-feedback-loop-r6-correction.md`, a audit i korigovane heatmape u `releases/feedback-loop-r6-correction-v1/`. Izvorna izvršenja i planovi nisu mijenjani.

## 3. F19 karakterizacija

Autoritativni zamrznuti model i prateći auditi su:

```text
artifacts/results/semantic-v2-model-freeze/
artifacts/results/semantic-v2-final-consistency/
releases/rq-alignment-v2/
```

`F19` koristi 19 semantički transformisanih pokazatelja za opis četiri kompozitna prototipa i mješovitih članstava. Taj prostor nije isto što i `P64->6`: F19 odgovara na pitanja o karakterizaciji, dok je PCA prostor sekundarni indeks za fizičku pretragu.

Raniji `F21-dev` razvojni model sa 21 pokazateljem ostaje objavljen radi historijske reprodukcije:

```text
releases/fcm-f21-development-v1/
```

Njegove silhouette i fuzzy metrike ne smiju se pripisati modelu `F19`. Podjelu automatski provjerava `python3 scripts/audit_clustering_lineage.py`.

Izvorni postupci za razvojni `F21-dev`, zamrzavanje `F19` i njegove vanjske provjere nalaze se u `sources/master-regimes/analysis/scripts/agent/17_m0_reduced_fuzzy_clustering.py` i datotekama `61_*` do `69_*`. Kratke tabele RQ1-RQ4 mogu se ponovo izgraditi naredbom `python3 scripts/build_rq_alignment_v2.py`.

## 4. Representation ablation

```text
releases/representation-ablation-e1-e4-v1/
releases/representation-value-ablation-v1/
```

Paket sadrži per-episode R1/R2/R3 izlaz, prag svake reprezentacije, trag susjeda, cluster-bootstrap intervale i leakage audit. Modelski ugovori nisu refitovani na završnim ili N3 panelima.

## 5. Završni i kontrolisani paneli

```text
releases/consolidated-evaluation-v1/
releases/confirmatory-action-replication-v1/
```

Konsolidovani release čuva dataset provenance, SQL/logical identitete, coverage-regret i robustness. Potvrdni release čuva pet ponavljanja, ordered result ugovor, frozen transfer, prequential i partial-feedback analizu.

Audit jedinica procjene i nesigurnosti potvrdnog panela nalazi se u:

```text
releases/action-selection-sample-size-audit-v1/
```

On eksplicitno pokazuje zašto 300 fizičkih izvršenja stabilizuje ishode 15 SQL odluka, ali ne stvara 300 nezavisnih Top-1 primjera.

Glavni nalaz nije univerzalna preporuka. Fizička pretraga može pronaći srodne slučajeve i nepokrivenost, ali novi panel nije potvrdio pouzdan cross-query prenos akcije.

## 6. Historijski actionability paket

```text
artifacts/results/pressure-actionability-v1/
```

Ovaj paket sadrži 418 parova, raniji colocation Ridge model i N3 no-refit audit. Zadržan je kao sekundarni historijski rezultat. Ne predstavlja primarni praktični izlaz trenutnog rada.

## 7. Logical indeksi i feature matrice

```bash
make extract-indexes
make feature-matrix CORPUS=clean-run-v1
```

Jedan red `execution_features.csv` predstavlja jedno `query_run_id` izvršavanje. Regionalni i worker/task fragmenti ostaju child tabele i ne broje se kao nezavisne opservacije.

## 8. Potpuna provjera paketa

```bash
make release-manifest
make verify
```

`make verify` provjerava katalog za ponovno izvođenje, raw/logical arhive, reprezentativne slučajeve, source scope, numeričke ugovore i globalni SHA-256 manifest. Ne pokreće bazu niti cloud infrastrukturu.
