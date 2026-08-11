# Mapa artefakata

## Navigacijski sloj

| Artefakt | Namjena |
| --- | --- |
| `reproducibility/query-catalog.csv` | jedan red po upakovanom renderovanom SQL fajlu |
| `reproducibility/dataset-catalog.csv` | veza dataseta sa profilom, generatorom, seedom i vremenom |
| `reproducibility/query-coverage.csv` | potpunost SQL pakovanja i označeni historijski izuzeci |
| `reproducibility/source-provenance.csv` | commitovi četiri izvršna repozitorija i rukopisa |
| `reproducibility/evidence-blocks.json` | eksperimentalni dizajn i putanje rezultata |

## Slojevi dokaza

| Sloj | Lokacija | Jedinica |
| --- | --- | --- |
| Renderovani SQL | `artifacts/rendered-corpora/` | SQL instanca ili ponovo korišteni SQL uslov |
| Raw attempt | `artifacts/raw-attempts/*.tar.gz` | fizičko pokretanje |
| Logical index | `artifacts/logical-indexes/*.tar.gz` | razrijesen logical run |
| Feature matrica | `artifacts/features/` | jedan red po `query_run_id` |
| Kurirani rezultat | `artifacts/results/` | numerički audit ili zamrznuti model |
| Autoritativni release | `releases/` | finalni CSV/JSON, figure i ugovori pojedinog eksperimenta |
| Studija slučaja | `examples/` | čitljiv SQL, plan, metrika i manifest |
| Planska ilustracija | `examples/PLAN-SOURCE-01/` | sanitizovani JSON planovi iza PEV2 prikaza iz rukopisa |

## Šema i skupovi podataka

- `sources/citus-datagen/sql/minimal_schema.sql`: izvršivi DDL, indeksi i Citus raspodjela sintetičke baze;
- `sources/citus-datagen/diagrams/current-schema-erd.svg`: ER prikaz istog ugovora;
- `datasets/dataset-index.csv`: veza `dataset_id` sa profilom, sjemenom, vremenskim osloncem i ugovorom regenerisanja;
- `sources/master-regimes/datasets/profiles/`: verzionisani profili stvarno korištenih skupova.

## Glavni rezultati

- `artifacts/results/pressure-actionability-v1/`: široki program, 418 parova i historijska colocation analiza;
- `artifacts/results/semantic-v2-model-freeze/`: autoritativni `F19`, centri, članstva i model manifest;
- `artifacts/results/semantic-v2-final-consistency/`: stabilnost, eksterni no-refit audit i profile prototipa za `F19`;
- `releases/rq-alignment-v2/`: kratki ulaz u RQ1-RQ4 brojeve, prototipe i konkretan mješoviti slučaj;
- `releases/fcm-f21-development-v1/`: historijski razvojni `F21-dev` sa izvornom matricom i rezultatima;
- `releases/model-lineage-audit-v1/`: provjera da se `F19`, razvojni `F21-dev` i `P64->6` ne miješaju;
- `releases/representation-ablation-e1-e4-v1/`: R1/R2/R3 po epizodi, susjedi, pragovi i leakage audit;
- `releases/representation-value-ablation-v1/`: dodatni absolute/relative pogled i sensitivity rezultati;
- `releases/consolidated-evaluation-v1/`: provenance, SQL identiteti, claim-evidence matrica, N2/N3 i `q08` analiza;
- `releases/confirmatory-action-replication-v1/`: pet ponavljanja novih SQL oblika, ordered-result audit i partial-feedback replay;
- `releases/action-selection-sample-size-audit-v1/`: jedinice procjene, Top-1 nazivnici i intervali nesigurnosti potvrdnog panela;
- `releases/retrieval-density-geometry-audit-v1/`: naknadna analiza veličine i sastava memorije, susjedstva i veze fizičke geometrije sa odzivom;
- `releases/feedback-loop-execution-v1/`: stvarne odluke, izvršenja, tranzicije, result audit i rollback;
- `releases/feedback-loop-analysis-v1/`: heatmape, stabilnost i lokalni replay;
- `releases/temporal-validity-audit-v1/`: audit zamrznutih i legacy vremenskih ugovora.

## Kanonske child tabele

- `query_runs.csv`: identitet, status i top-level metapodaci izvršavanja;
- `execution_features.csv`: izvedeni execution-level pokazatelji;
- `region_fragments.csv`: regionalni fragmenti;
- `worker_task_fragments.csv`: Citus task fragmenti;
- `plan_nodes.csv` i `plan_edges.csv`: normalizovana stabla planova;
- `query_bindings.csv`: renderovani parametri;
- `plan_files.csv`: veza sa izvornim JSON ili tekstualnim planom.

Regionalni i worker redovi nisu zasebne ML opservacije. Oni pripadaju istom `query_run_id` i iz njih nastaje jedno rekonstruisano fizičko stanje.

## SQL napomene

Glavni noviji paneli sadrže puni SQL direktno u `artifacts/rendered-corpora/`. `confirmatory-skew-v1` je jedini stariji slučaj u kojem SQL nije ostao uz render manifest; 48 stvarno izvršenih fajlova izdvojeno je iz objavljene raw arhive. `repeatability-v1` namjerno ponovo koristi SQL iz drugih corpusa. Ove razlike su mašinski označene u `reproducibility/query-coverage.csv`.
