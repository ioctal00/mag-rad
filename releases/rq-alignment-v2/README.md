# RQ1-RQ4 evidence for the promoted F19 model

This directory is the short, public entry point for the clustering results used in the thesis. It is generated from the frozen F19 model and does not refit any model.

## Start here

- [`model_summary.csv`](model_summary.csv) contains the F19 results for three and four prototypes.
- [`prototype_summary.csv`](prototype_summary.csv) gives the descriptive names used in the thesis.
- [`membership_quality.csv`](membership_quality.csv) reproduces the 1,847 clear, 69 mixed and 48 weak cases.
- [`mixed_case_memberships.csv`](mixed_case_memberships.csv) contains the concrete mixed execution used in the thesis.
- [`mixed_case_feature_support.csv`](mixed_case_feature_support.csv) shows which F19 coordinates move that execution toward its leading and competing prototypes.
- [`promotion_gates.csv`](promotion_gates.csv) records the frozen checks that promoted F19.

The complete 19-feature contract is [`configs/features/feature_semantic_contract_v2.yml`](../../configs/features/feature_semantic_contract_v2.yml). Frozen centers and memberships are in [`artifacts/results/semantic-v2-model-freeze/`](../../artifacts/results/semantic-v2-model-freeze/). Transfer, repeatability and leave-family-out audits are in [`artifacts/results/semantic-v2-final-consistency/`](../../artifacts/results/semantic-v2-final-consistency/).

## Keep the three spaces separate

- **F19** is the promoted 19-feature FCM representation used for RQ1-RQ4.
- **F21-development** is the earlier 21-feature development ablation in [`../fcm-f21-development-v1/`](../fcm-f21-development-v1/).
- **P64-to-6** is the separate PCA/kNN intervention-memory space. Its FCM comparator is not the F19 model.

Silhouette values from F19 and F21-development are calculated in different feature spaces and are not a direct head-to-head score.

## Rebuild

```bash
python3 scripts/build_rq_alignment_v2.py
python3 scripts/audit_clustering_lineage.py
(cd releases/rq-alignment-v2 && sha256sum -c checksums.sha256)
```

No SQL execution, dataset regeneration or model refit is performed by these commands.
