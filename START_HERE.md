# Gdje se šta nalazi

Za pregled rada nisu potrebni interni nazivi direktorija.

| Tražim | Otvoriti |
| --- | --- |
| LLM vodič za pronalazak i objašnjenje artefakata rada | [`skills/navigate-master-thesis/`](skills/navigate-master-thesis/) |
| SQL `q07`, `q08` ili drugi `q01`-`q30` | [`queries/`](queries/) |
| sve tačno renderovane SQL instance | [`reproducibility/query-catalog.csv`](reproducibility/query-catalog.csv) |
| SQL šablone | [`queries/template-index.csv`](queries/template-index.csv) |
| dataset profile i sjeme | [`datasets/`](datasets/) |
| izvršivi DDL, Citus raspodjela i indeksi sintetičke baze | [`sources/citus-datagen/sql/minimal_schema.sql`](sources/citus-datagen/sql/minimal_schema.sql) |
| ER dijagram sintetičke baze | [`sources/citus-datagen/diagrams/current-schema-erd.svg`](sources/citus-datagen/diagrams/current-schema-erd.svg) |
| corpus i njegov rezultat | [`corpora/`](corpora/) |
| čitljiv prije/poslije primjer | [`examples/`](examples/) |
| JSON planovi iza PEV2 prikaza u radu | [`examples/PLAN-SOURCE-01/`](examples/PLAN-SOURCE-01/) |
| vrijednosti iza F19 tabela za RQ1-RQ4 | [`releases/rq-alignment-v2/`](releases/rq-alignment-v2/) |
| P64->6 izbor pokazatelja i zamrznuti ugovor | [`analysis/reports/fuzzy-intervention-memory-v1/feature_selection_audit.csv`](analysis/reports/fuzzy-intervention-memory-v1/feature_selection_audit.csv) i [`configs/models/fuzzy_intervention_memory_v1.yml`](configs/models/fuzzy_intervention_memory_v1.yml) |
| audit 418 parova i trinaest intervencija | [`analysis/reports/pressure-raw-v1-mitigation-action-audit/`](analysis/reports/pressure-raw-v1-mitigation-action-audit/) |
| longitudinalne putanje, rollback i heatmape | [`releases/feedback-loop-execution-v1/`](releases/feedback-loop-execution-v1/), [`releases/feedback-loop-analysis-v1/`](releases/feedback-loop-analysis-v1/) i [ispravka šeste R6 domene](docs/05-feedback-loop-r6-correction.md) |
| sekundarni panel ponovne upotrebe i njegov `q08` primjer | [`releases/consolidated-evaluation-v1/`](releases/consolidated-evaluation-v1/), [`releases/confirmatory-action-replication-v1/`](releases/confirmatory-action-replication-v1/) i [`examples/Q08-NEIGHBORS/`](examples/Q08-NEIGHBORS/) |
| zašto 300 izvršenja daje 15 SQL odluka, a ne 300 Top-1 primjera | [`releases/action-selection-sample-size-audit-v1/`](releases/action-selection-sample-size-audit-v1/) |
| naknadna provjera veličine i sastava sekundarne memorije | [`releases/retrieval-density-geometry-audit-v1/`](releases/retrieval-density-geometry-audit-v1/) |
| audit vremenskih izraza i presjeka | [`releases/temporal-validity-audit-v1/`](releases/temporal-validity-audit-v1/) |
| Terraform i Ansible | [`sources/master-regimes-infra/`](sources/master-regimes-infra/) |
| generator sintetičkih podataka | [`sources/citus-datagen/`](sources/citus-datagen/) |
| potpuni audit ponovljivosti | [`reproducibility/audits/REPRODUCIBILITY_AUDIT.md`](reproducibility/audits/REPRODUCIBILITY_AUDIT.md) |

Oznake `q01`-`q30` lokalne su eksperimentalnom panelu. Puni naziv i corpus uvijek su autoritativni. Primjer: `q07_tenant_count` iz N3 panela nije isto što i historijski šablon `q07_global_user_segment_join` iz karakterizacijskog corpusa.

Oznake `S1`-`S6` iz rukopisa grupišu dodatne artefakte. Tabela iznad vodi direktno do najčešće korištenih izvora sa stranica metodologije i rezultata; potpuna podjela releasea data je u [`docs/04-artifact-map.md`](docs/04-artifact-map.md).

Komanda `make public-check` ponovo gradi ovu navigaciju, provjerava njene veze i odbija paket koji sadrži lokalne home putanje, tajne ili runtime IP adrese u objavljenim podacima.

Komanda `make public-audit-full` dodatno provjerava sadržaj kompresovanih arhiva i već objavljenu Git historiju.
