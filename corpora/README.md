# Eksperimentalni corpusi

Ovaj direktorij povezuje naziv corpusa sa tačnim SQL ulazom i rezultatom. Interni razvojni manifesti ostaju u izvornom snapshotu, dok su ovdje izdvojeni samo corpusi potrebni za čitanje i provjeru rada.

| Corpus | Uloga | SQL | Rezultat |
| --- | --- | --- | --- |
| `clean-run-v1` | završna F19 karakterizacija i historijska F21-dev ablacija | [`SQL`](../artifacts/rendered-corpora/clean-run-v1) | [`izlaz`](../releases/rq-alignment-v2) |
| `pressure-raw-v1` | široki intervencijski corpus | [`SQL`](../artifacts/rendered-corpora/pressure-raw-v1) | [`izlaz`](../artifacts/results/pressure-actionability-v1) |
| `dba-local-memory-v1` | završni DBA panel | [`SQL`](../artifacts/rendered-corpora/dba-local-memory-v1) | [`izlaz`](../releases/consolidated-evaluation-v1) |
| `n3-topology-memory-v1` | kontrolisani N2/N3 panel | [`SQL`](../artifacts/rendered-corpora/n3-topology-memory-v1) | [`izlaz`](../releases/consolidated-evaluation-v1) |
| `confirmatory-action-replication-v1` | potvrdni panel q16-q30 | [`SQL`](../artifacts/rendered-corpora/confirmatory-action-replication-v1) | [`izlaz`](../releases/confirmatory-action-replication-v1) |
| `feedback-loop-v1` | longitudinalne DBA putanje | [`SQL`](../artifacts/rendered-corpora/feedback-loop-v1) | [`izlaz`](../releases/feedback-loop-analysis-v1) |
| `region-asymmetry-companion-v1` | regionalna asimetrija | [`SQL`](../artifacts/rendered-corpora/region-asymmetry-companion-v1) | [`izlaz`](../artifacts/features/clean-run-v1-region-asymmetry) |
| `wan-latency-companion-v1` | mrežna osjetljivost | [`SQL`](../artifacts/rendered-corpora/wan-latency-companion-v1) | [`izlaz`](../artifacts/logical-indexes/clean-run-v1-wan-latency.tar.gz) |
| `repeatability-v1` | ponovljivost odabranih stanja | [`SQL`](../artifacts/rendered-corpora/repeatability-v1) | [`izlaz`](../artifacts/results/repeatability-v1) |
| `validation-holdout-v1` | validacijski holdout | [`SQL`](../artifacts/rendered-corpora/validation-holdout-v1) | [`izlaz`](../artifacts/features/clean-run-v1-validation-holdout) |
| `confirmatory-skew-v1` | potvrdni skew panel | [`SQL`](../artifacts/rendered-corpora/confirmatory-skew-v1) | [`izlaz`](../artifacts/features/confirmatory-skew-v1) |
| `stats-ceb-semantic-v2b-holdout` | vanjski semantic holdout | [`SQL`](../artifacts/rendered-corpora/stats-ceb-semantic-v2b-holdout) | [`izlaz`](../artifacts/features/stats-ceb-semantic-v2b-holdout) |
| `stats-ceb-full-no-refit-v1` | puni STATS-CEB audit | [`SQL`](../artifacts/rendered-corpora/stats-ceb-full-no-refit-v1) | [`izlaz`](../artifacts/features/stats-ceb-full-no-refit-v1) |
| `pressure-raw-v1-n3-colocation-holdout` | historijski N3 colocation holdout | [`SQL`](../artifacts/rendered-corpora/pressure-raw-v1-n3-colocation-holdout) | [`izlaz`](../artifacts/results/pressure-actionability-v1) |

Mašinski čitljiva verzija tabele je u [`corpus-index.csv`](corpus-index.csv). Pojedinačne SQL instance mogu se tražiti kroz [`queries/`](../queries/).
