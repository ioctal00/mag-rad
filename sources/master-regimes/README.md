# master-regimes

Centralni repozitorij za novi magistarski pipeline:

```text
regime corpus + SQL template + parametri + dataset profil + runtime konfiguracija
+ EXPLAIN JSON + mjerenja + Citus metadata
-> pokazatelji
-> rezimi izvrsavanja
-> objasnjivi izvjestaji
```

Ovaj repo ne pokusava zamijeniti infrastrukturu, generator podataka ili stare benchmark alate. Njegova uloga je da ih orkestrira i normalizuje njihove artefakte u jedan evidence pipeline.

## Layout

| Putanja | Namjena |
| --- | --- |
| `EXPERIMENTS.md` | Aktuelna navigacija kroz eksperimente, release pakete i tvrdnje završnog rukopisa. |
| `configs/systems/` | Opisi topologija koje ulaze u run manifest. |
| `configs/sweeps/` | Smoke, pilot, medium i intervention sweep konfiguracije. |
| `datasets/profiles/` | Dataset profili i capability ugovori. |
| `workloads/` | Registry SQL sablona, parametarski prostori i Jinja SQL. |
| `generated/workloads/` | Renderovane SQL instance i `instance_manifest.csv`; ulaz za infra execution runove. |
| `runs/` | Legacy/compat output za starije lokalne render komande; ne koristiti za nove workload-e. |
| `extract/` | Plan/parser i feature extraction razvojni prostor. |
| `models/` | Offline modeliranje i validacija. |
| `releases/` | Verzionski zaključani, mašinski čitljivi eksperimentalni paketi i checksum manifesti. |
| `outputs/final/` | Stariji kurirani izlazi. Za aktuelne tvrdnje prvo koristi `releases/consolidated-evaluation-v1/`. |
| `src/master_regimes/` | Python CLI i biblioteka. |

## Brzi start

```bash
uv python install 3.14.5
uv venv
uv sync

uv run master-regimes doctor
uv run master-regimes init-run \
  --system configs/systems/eu-us-gac.example.yml \
  --dataset datasets/profiles/smoke.yml \
  --sweep configs/sweeps/smoke.yml

uv run master-regimes render-workload \
  --registry workloads/suites/single-region-core.yml \
  --out generated/workloads/single-region-core/dev

uv run master-regimes index-query-sweep \
  --sweep-dir ../master-regimes-infra/generated/runs/query-sweeps/<sweep-id>

uv run master-regimes index-analytics-fdw \
  --run-dir ../analytics-client/runs/<run-id>

uv run master-regimes build-feature-matrix \
  --index-dir ../master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs/<logical-run-id>/_index \
  --out analysis/features/<logical-run-id> \
  --topology multi_region

uv run master-regimes prepare-clustering-dataset \
  --features-dir analysis/features/<logical-run-id> \
  --out-dir analysis/features/<logical-run-id>/preprocessed
```

Ako Python `3.14.5` nije instaliran, `doctor` ce to prijaviti. Kod je namjerno pisan tako da pocetni skelet moze proci staticku provjeru i prije stvarnog cloud runa.

## Granice

- `citus-datagen` ostaje generator podataka.
- `master-regimes-infra` ostaje Terraform/Ansible infrastruktura.
- `analytics-client` ostaje kandidat za GAC/FDW runtime adapter.
- Ovaj repo definise kanonski vokabular, corpus/cell ID-jeve, manifeste, feature tabelu, modele i finalne izvjestaje.

Kanonski vokabular je u `docs/corpus-vocabulary.md`. U njemu je zaključano da `query_sweep` i `database_sweep` ostaju execution backend termini, dok se eksperimentalni dizajn vodi kroz `corpus_id`, `corpus_cell_id`, `logical_question_id`, `execution_strategy`, `dataset_profile_id`, `runtime_config_id` i `intervention_role`.

## Workload Izvor Istine

Kanonski SQL workload-i su u ovom repozitoriju:

```text
workloads/templates/<domain>/*.sql.j2
workloads/suites/*.yml
generated/workloads/<suite-id>/<render-id>/instance_manifest.csv
```

Kanonski vokabular za corpus/cell sloj je u `docs/corpus-vocabulary.md`. Novi suite/template metadata mora razlikovati:

- `logical_question_id`: analitičku namjeru;
- `execution_strategy`: način izvršenja iste namjere;
- `template_id`: konkretni SQL šablon;
- `instance_id`: renderovanu parametrizovanu instancu;
- `runtime_sensitivity`: gdje `fetch_size`, `work_mem` ili WAN intervencije imaju smisla.

Prvi kontrolisani pre-US corpus manifest je:

```text
workloads/corpus/corpus_manifest.pre-us-pilot.yml
```

Pre-clustering decision gate-ovi su:

```text
workloads/corpus/regime-coverage.yml
workloads/corpus/dataset-schema-decision.yml
```

`regime-coverage.yml` mapira ciljne režime na query porodice, template-e, dataset capability-je i runtime ose. `dataset-schema-decision.yml` odlučuje da li trenutni `citus-datagen` schema/profili mogu proizvesti potrebne signale. Trenutna odluka je da se prvo jačaju profili/auditi, bez schema promjene.

Manualni pre-feature-extraction clean-run workflow je dokumentovan u:

```text
docs/clean-run-readiness.md
```

Lokalno zaključani repeatability workflow koristi 96 uslova i 328 izvršenja. Prije infrastrukture provjerava se sa `make repeatability-local-gate` i `make repeatability-smoke-infra-dry-run`. Nakon stvarnog runa, `make repeatability-analyze` indeksira attempt-e, gradi feature matricu, projektuje izvršenja kroz tada zaključani V1 model sa 21 pokazateljem bez refitovanja i piše condition-level izvještaj o stabilnosti. Konačna teza naknadno promoviše semantički V2 model sa 19 pokazatelja; V1 rezultat ostaje historijski baseline za ablacijsku analizu.

Završni rukopis i thesis-ready paketi provjeravaju se jednom naredbom:

```bash
make check-thesis
```

Ovaj target pokreće testove, eksplicitno ograničeni završni Ruff scope, clean-room regenerisanje rezultata, audit brojki i tvrdnji, formalni audit rukopisa te build rada i odbrane. Širi `make lint` obuhvata i historijske notebook/legacy skripte i zato nije prikazan kao prolaz završnog paketa.

Aktuelna mapa eksperimenata i dokaza koji se prikazuju u završnom rukopisu je:

```text
EXPERIMENTS.md
```

Ona je početna tačka za provenance, četiri eksperimentalna skupa, representation-ablation, kontrolisani N2/N3 panel, SQL/logičke memorijske ključeve, q08 analizu i veze prema rukopisu.

Starija mapa baseline, holdout i companion artefakata je u:

```text
docs/run-artifact-navigation-map.md
```

Ona opisuje historijsku FCM fazu: koji logical run ulazi u tadašnji model, koji runovi su companion sloj i kako provjeriti da feature matrice nisu pomiješale pogrešne `_index` direktorije. Ne koristiti je kao zamjenu za aktuelni `EXPERIMENTS.md`.

Njegov source manifest je `workloads/corpus/corpus_manifest.clean-run-v1.yml`; trenutno renderuje 1964 `pilot` instance u 8 segmentisanih execution grupa. Optional `long_budget` legacy ćelije postoje za svjesno proširenje rendera, ali nisu dio default clean-run targeta.

Runtime intervencije su odvojene u katalog:

```text
workloads/corpus/runtime-configs.yml
```

Corpus manifest ga referencira kroz `runtime_catalog`. `fetch_small` i `fetch_large` mijenjaju `postgres_fdw` server opciju `fetch_size`, dok `work_mem_low` i `work_mem_high` idu kroz session `PGOPTIONS`. Validator odbija `positive_case` runtime ćelije ako template nema odgovarajuću `runtime_sensitivity: high`, a `negative_control` dozvoljava samo template-e sa `low` ili `none` osjetljivošću na toj osi.

Validacija:

```bash
uv run master-regimes validate-corpus \
  --manifest workloads/corpus/corpus_manifest.pre-us-pilot.yml

uv run master-regimes validate-dataset-profile \
  --profile datasets/profiles/geo-skew-heavy.yml
```

Render u execution artefakte za `master-regimes-infra`:

```bash
uv run master-regimes render-corpus \
  --manifest workloads/corpus/corpus_manifest.pre-us-pilot.yml \
  --out generated/corpus/pre-us-pilot \
  --max-instances-per-cell 1
```

Ovo piše `corpus_execution_plan.yml`, kopiju `corpus_manifest.yml`, `corpus_cells.csv`, per-group `instance_manifest.csv`, renderovane SQL fajlove i `sweeps/*.yml` koje infra database-sweep runner može pokrenuti. Adapter grupiše ćelije po dataset profilu, runtime configu i target grupi, tako da `single_region_citus` i GAC/analytics ćelije ne završe u istom backend sweepu.

Generisani `sweeps/*.yml` prenose `pg_options`, `psql_variables`, `fdw_server_options`, `intervention_axis` i `expected_effect` u `master-regimes-infra`. Time runtime promjena ostaje traceable context/audit signal, ali nije default input za clustering.

`corpus_cells.csv` je dimenzijska tabela za corpus dizajn. Nakon izvršenja, `index-query-sweep` i database-sweep index pišu vlastiti `_index/corpus_cells.csv`, dok `query_runs.csv` ostaje fact tabela. Join key je `corpus_cell_id` (`database_sweep_id, corpus_cell_id` na database-sweep nivou).

Izvršenje renderovanog corpusa ide kroz postojeći infra backend, ne kroz novi runner u ovom repozitoriju:

```bash
cd ../master-regimes-infra
make eu-us-gac-vps-corpus-run \
  CORPUS_EXECUTION_PLAN=../master-regimes/generated/corpus/pre-us-pilot/corpus_execution_plan.yml \
  CORPUS_RUN_LABEL=pre-us-pilot \
  CORPUS_RUN_DRY_RUN=true
```

Bez `CORPUS_RUN_DRY_RUN=true`, wrapper sekvencijalno pokreće generated `sweeps/*.yml` kroz postojeći `run_database_sweep.py`. Svaka grupa ostaje normalan database sweep sa vlastitim `_index`.

Manifest je dizajn/cell sloj. Execution backend i dalje može koristiti database sweep zbog efikasnog grupisanja po dataset/runtime koracima, ali corpus ćelije određuju zašto se kombinacija pokreće.

Dataset profili su capability ugovori, ne samo veličine. Svaki profil mora deklarisati `expected_audit_signals`; infra dataset-load zatim zapisuje `capability_audit.json` i `dataset_parameter_values.json`. Sa audit fajlom se može pokrenuti:

```bash
uv run master-regimes validate-dataset-profile \
  --profile datasets/profiles/geo-skew-heavy.yml \
  --audit ../master-regimes-infra/generated/runs/dataset-loads/<load-id>/capability_audit.json
```

Važna terminologija:

- `generated/workloads/**` u ovom repozitoriju su renderovane SQL instance.
- `master-regimes-infra/generated/runs/**` su stvarni execution outputi, planovi, manifesti i `_index` tabele.
- `master-regimes/runs/**` je legacy naziv iz ranijih iteracija i ne treba se koristiti za nove pipeline korake.

`psql-benchmarks` samo izvrsava renderovane SQL instance i skuplja EXPLAIN artefakte. `master-regimes-infra` orkestrira udaljene runove i zapisuje generated artefakte. `analytics-client/sql/queries/**` nije izvor istine za master workload; taj folder je legacy/runtime adapter za analytics-client eksperimente.

Prije širenja corpusa koristi `docs/feature-readiness.md` kao kapiju: extractor treba citati `_index/*.csv`, a ne direktno duboke raw foldere. Dokument eksplicitno biljezi da su US region i `fdw_us` aktivni za smoke-level provjere, ali da finalni multi-region/WAN zaključci još traže veći Plan C corpus. `fetch_share` u prvoj verziji ostaje proxy kroz `remote_path_share`, ne čisti network-transfer signal.

Katalog pokazatelja koje extractor treba izvesti je u `docs/metric-dictionary.md`: tamo su razdvojeni `core_v1`, proxy, database sweep context, GAC/US-later i optional debug signali. Mašinski contract za izbor model inputa je `docs/feature_schema.yml`; svaki `index-query-sweep` ga kopira u `_index/feature_schema.yml`.

`build-feature-matrix` je kanonski feature extractor za podplan 8. Čita normalizovani `_index`, agregira `plan_nodes.csv`, `fdw_remote_plans.csv` i `plan_structure_features.csv`, te piše:

```text
features/execution_features_m0.csv   # core_model_v1 behavioral baseline
features/execution_features_m1.csv   # M0 + plan_structure_v1 ablation
features/model_context.csv           # ID/context/audit/validation/quality cols
features/feature_catalog_m0.csv
features/feature_catalog_m1.csv
features/feature_quality_report.csv
features/categorical_expansions.csv
features/feature_matrix_manifest.yml
```

Default izlaz je `<index-dir>/features`; koristi `--out-dir` kada ne želiš pisati u generated run. Komanda ne pokreće ML i ne planira eksperimente. Ona samo materijalizuje model matrice prema schema contractu.

`prepare-clustering-dataset` je quality/preprocessing gate iznad tog sloja. Čita `features/`, izbacuje neuspjele/time-out/warmup redove, uklanja ne-numeričke, konstantne i previše rijetke feature-e, radi median imputaciju bez pretvaranja `NULL` u nulu, dodaje `__is_missing` indikatore kada je nedostupnost varijabilna i standardizuje numeričke kolone. Default izlaz je:

```text
features/clustering/clustering_input_m0.csv
features/clustering/clustering_input_m1.csv
features/clustering/clustering_context.csv
features/clustering/row_filter_report.csv
features/clustering/feature_preprocessing_report.csv
features/clustering/dropped_features.csv
features/clustering/clustering_readiness_report.csv
features/clustering/clustering_dataset_manifest.yml
```

Make target `make clustering-dataset` koristi eksplicitni `--out-dir` i piše iste fajlove u:

```text
analysis/features/<logical-run-id>/preprocessed/
```

Dakle, `clustering/` i `preprocessed/` nisu dva formata; razlika je samo u izabranom output direktoriju.

Ovaj korak još uvijek ne pokreće fuzzy clustering. Njegova uloga je da napravi model-ready M0/M1 matrice i jasan audit zašto je neki red ili feature isključen. `clustering_readiness_report.csv` dodatno označava kada je matrica premala ili ima previše feature-a u odnosu na broj redova; to je stop-signal za pravi clustering, ali ne za parser/preprocessing smoke.

Za corpus runove sa rerun pokušajima ne gradi feature matrix nad pojedinačnim database-sweep `_index` folderom. Prvo izgradi logical index u `master-regimes-infra`, pa koristi njegov `_index` kao kanonski input:

```bash
make logical-run-index LOGICAL_RUN_ID=<logical-run-id>
make feature-matrix LOGICAL_RUN_ID=<logical-run-id> FEATURE_TOPOLOGY=multi_region
make clustering-dataset LOGICAL_RUN_ID=<logical-run-id>
make clustering-ready-gates LOGICAL_RUN_ID=<logical-run-id>
make corpus-coverage-gate LOGICAL_RUN_ID=<logical-run-id>
```

Ili sve zajedno:

```bash
make clustering-ready-audit LOGICAL_RUN_ID=<logical-run-id>
```

`clustering-ready-audit` sada radi i Phase 12 corpus coverage gate nad `workloads/corpus/corpus_manifest.plan-c-pilot.yml`. Phase 12 provjerava dva sloja: planirani corpus coverage iz manifesta i observed completed coverage iz logical `_index` redova. Ako želiš provjeriti drugi manifest, proslijedi `CORPUS_MANIFEST=<path>` i po potrebi `CORPUS_COVERAGE=<path>`.

Coverage gate koristi isti execution-class scope kao corpus renderer. Default je `CORPUS_INCLUDE_EXECUTION_CLASS=pilot`, pa `long_budget` ćelije nisu obavezne za bounded pilot readiness. Kada želiš provjeriti i sporije ćelije:

```bash
make clustering-ready-audit \
  LOGICAL_RUN_ID=<logical-run-id> \
  CORPUS_INCLUDE_EXECUTION_CLASS=pilot,long_budget
```

Za finalni manifest-level audit može se koristiti `CORPUS_INCLUDE_EXECUTION_CLASS=all`.

Logical index se nalazi u:

```text
../master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs/<logical-run-id>/_index/
```

On bira najbolji completed attempt za svaku corpus instancu, spaja originalni run i rerun segmente, i zadržava princip:

```text
jedan query_run_id = jedan clustering red
region_fragments.csv i worker_task_fragments.csv = child evidence
```

`expected_regime_targets`, `pressure_tags`, `logical_question_id`, `execution_strategy`, `dataset_profile_id`, `runtime_config_id` i `intervention_role` su context/validation polja. Ona služe za dizajn corpusa, traceability i validaciju, ali nisu default inputi za unsupervised model.

Za brzu provjeru parsera koristi `workloads/suites/gac-parser-smoke.yml`; on namjerno pokriva FDW aggregate, FDW join i lokalni ETL query u samo tri instance.

## Trenutni readiness status

Referentni N+1/worker parser i preprocessing pilot je logical corpus run:

```text
logical_run_id:
  plan-c-bounded-pilot
logical_index:
  ../master-regimes-infra/generated/runs/corpus-sweeps/_logical-runs/
  plan-c-bounded-pilot/_index
feature_matrix:
  analysis/features/plan-c-bounded-pilot
reports:
  analysis/reports/plan-c-bounded-pilot-logical/
```

Njegov logical `_index/` ima 34 query runa, 52 regionalna fragmenta i 1199 Citus worker/task fragmenata. `execution_features_m0.csv` i `execution_features_m1.csv` imaju po 34 reda, dakle regionalni i worker planovi ne eksplodiraju clustering matricu.

Phase 11 odluka je `parser_ready_but_sample_small`, a `prepare-clustering-dataset` status je `ready`. Phase 12 nad Plan C manifestom je `ready_with_caveats`: planirani coverage je dobar, a observed completed coverage pokazuje koje planirane ćelije još treba rerun/long-budget pokušaj. To znači da je parser/collector i single-row feature representation spreman za širenje corpusa, ali 34 reda nisu dovoljna za ozbiljan fuzzy clustering.

Agent-side QA skripte su u `analysis/scripts/agent/`:

```bash
uv run python analysis/scripts/agent/run_all.py \
  --index-dir ../master-regimes-infra/generated/runs/database-sweeps/<sweep-id>/_index \
  --manifest workloads/corpus/corpus_manifest.pre-us-pilot.yml \
  --llm-validation-pack
```

One generišu lokalne izvještaje u `analysis/reports/<sweep-id>/`. Posebno je važan `03_feature_matrix_profile.md`: trenutno pokazuje da su M0 izvori sačuvani u `_index`, ali da dio kolona još treba agregirati u stvarnom feature extractor-u.

Corpus QA gate je u fazama 07-09:

- `07_corpus_design_review.md`: provjerava da corpus ćelije imaju razlog, očekivani režim, runtime relevantnost i dataset capability pokriće;
- `08_intervention_contrast_review.md`: poredi baseline/positive/negative runtime intervencije kada postoje observed `_index` redovi;
- `09_pairing_coverage_review.md`: provjerava da logical-question porodice imaju parove strategija, posebno FDW i ETL/materialized varijante.

Ako se doda `--llm-validation-pack`, isti pipeline piše i:

```text
analysis/reports/<sweep-id>/llm_validation_pack/
```

Tu su sekvencijalni promptovi za LLM/MCP review: artefact integrity, corpus design, intervention contrast, pairing coverage, feature readiness i finalna odluka. Promptovi su pomoćni reviewer sloj nad programskim izvještajima; nisu kanonski feature extractor.

EU+US+GAC regioni su aktivni za Plan C pilot. Za feature-matrix izbor koristi `--topology multi_region`, jer GAC query može imati N+1 planova: GAC/main plan plus regionalni EU/US remote planovi.

## STATS-CEB portability pilot

Ograničeni vanjski pilot koristi javni STATS-CEB paket bez originalnog modificiranog CardEst sistema. Izvor, osam upita i fizički Citus dizajn su zaključani u `external/stats-ceb/`.

```bash
make stats-ceb-local-gate
make stats-ceb-render
make stats-ceb-infra-dry-run
```

Stvarni `make stats-ceb-start` radi tek nakon pregleda prepare/correctness izlaza. Snapshot je identičan u EU i US; svaki regionalni rezultat poredi se sa GAC baselineom i regionalni `COUNT(*)` rezultati se ne sabiraju. Pilot ne mijenja 21-feature ugovor i ne trenira FCM ponovo.

Nakon izvršenja:

```bash
make stats-ceb-analyze
```

Komanda spaja attempt u logical run, gradi postojeću multi-region feature matricu i izvodi Plan 21 portability/frozen-projection audit. Fuzzy projekcija je deskriptivna; apsolutna udaljenost do zaključanih centara prijavljuje se odvojeno.

Lokalni representation audit za Plan 22 ne pokreće infrastrukturu i ne mijenja zaključani model:

```bash
make stats-ceb-representation-audit
```

Audit rastavlja `q100` OOD udaljenost po feature-ima, provjerava distribuciju, applicability i redundanciju svih 21 pokazatelja te eksploratorno poredi frozen StandardScaler prostor sa semantički definisanom normalizacijom koja ne zavisi od distribucije korpusa. FCM prototipi u oba slučaja ostaju uslovljeni originalnim trening korpusom. Rezultati se pišu u `analysis/reports/stats-ceb-representation-audit-v1/`.

Nakon zamrzavanja semantičkog V2 ugovora i potvrđujućeg V2b holdouta, kompletan lokalni consistency paket pokreće se sa:

```bash
make semantic-v2-final-consistency
```

Paket ne pokreće infrastrukturu niti ponovo uči model. Finalna odluka je `PROMOTE_V2_WITH_LIMITED_FUZZY_CLAIM`: 19-dimenzionalni semantički prostor postaje finalni modelski ulaz, a empirijski standardizovani prostor od 21 pokazatelja ostaje baseline za ablacijsku analizu. Sirovi izvedeni sloj ostaje autoritativan za fizičke magnitude i signale koje fuzzy članstva mogu sabiti.

Puni vanjski audit koristi svih 146 upita iz zaključane STATS-CEB arhive. Izbor upita, 19 pokazatelja, transformacije, porodične težine, `k=4`, centri, `m=1.7` i P99 prag moraju ostati zamrznuti prije izvršavanja:

```bash
make stats-ceb-full-local-gate
make stats-ceb-full-infra-dry-run
make stats-ceb-full-start
make stats-ceb-full-analyze
make stats-ceb-fuzzifier-sensitivity
```

Correctness korak pokušava svih 146 upita i čuva svaki status, ali collector izvršava samo upite čiji se skalarni rezultat poklapa sa baselineom unutar unaprijed definisanog timeouta. Offline fuzzifier audit koristi `m in {1.5, 1.7, 2.0}` bez promjene finalnog modela i bez ponovnog SQL runa. Puni audit je provjera vanjske no-refit pokrivenosti, a ne novi trening korpus ili dokaz univerzalnih prototipa.

Prilozi, ugovor ponovljivosti, terminologija i prezentacija zatim se provjeravaju lokalnim Plan 28 gateom:

```bash
make semantic-v2-thesis-defense
```

Ako se koristi `analytics-client` kao FDW runtime adapter, njegov `explain-fdw`/`snapshot-fdw-options` output se ne parsira ručnim obilaskom foldera. Koristi `index-analytics-fdw`; taj bridge piše `analytics_fdw_features.csv` i `analytics_fdw_options.csv` u `_index` direktorij i čuva vezu prema `template_id`, `instance_id`, `execution_id`, FDW klasifikaciji i postgres_fdw opcijama bez tajni.
