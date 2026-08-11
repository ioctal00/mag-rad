# Model lineage audit

Run:

```bash
python3 scripts/audit_clustering_lineage.py
```

The audit prevents three numerical spaces from being conflated:

- `F19` is the final semantic-V2 FCM characterization used for RQ1-RQ4.
- `F21-development` is the earlier 21-feature FCM ablation.
- `P64->6` is the independent PCA space used by the secondary kNN and prototype-memory evaluation.

The generated JSON and CSV files verify dimensions, fit scopes, core metrics, membership-category counts, the P64->6 leakage gate and feature overlap.
