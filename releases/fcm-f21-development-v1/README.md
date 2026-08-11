# F21 development model

This directory preserves the earlier 21-feature FCM experiment exactly as a development artifact. It is not the authoritative FCM representation used for the final RQ1-RQ4 answers.

The experiment used 1,964 `clean-run-v1` rows, 21 standardized features, `m=1.7`, ten seeds and `k in {4,5}`. Its mean hard-label silhouette was `0.213960` for `k=4` and `0.225171` for `k=5`. These values belong only to this F21 geometry.

The later semantic-V2 model reduced the representation to 19 bounded and family-weighted features. That F19 model is stored under [`artifacts/results/semantic-v2-model-freeze/`](../../artifacts/results/semantic-v2-model-freeze/) and is the authoritative characterization model.

Files in this directory were recovered from the pre-cleanup snapshot and verified by an exact offline refit. The source matrix, memberships, centers and all substantive metrics matched the archived outputs byte for byte. Runtime-only progress fields were not copied.

The original feature contract remains available at [`sources/master-regimes/configs/features/phase1_flow_ratio_candidate.yml`](../../sources/master-regimes/configs/features/phase1_flow_ratio_candidate.yml).

## Offline refit

From the repository root, the archived input can be refit without executing SQL:

```bash
(cd sources/master-regimes && uv run python \
  analysis/scripts/agent/17_m0_reduced_fuzzy_clustering.py \
  --candidate configs/features/phase1_flow_ratio_candidate.yml \
  --matrix ../../releases/fcm-f21-development-v1/source_matrix.csv \
  --context ../../releases/fcm-f21-development-v1/context.csv \
  --out-dir ../../build/f21-development \
  --k-values 4,5 \
  --seeds 0..9 \
  --no-plots)
```

The fitted centers, memberships and substantive score tables should match the archived files. Runtime and progress-log fields are machine-dependent and are not part of that comparison.
