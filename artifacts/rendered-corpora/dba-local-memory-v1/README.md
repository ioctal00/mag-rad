# Corpus Execution Plan

Generated from a controlled `corpus_manifest.yml`. Each group is an infra-compatible database sweep that shares one dataset profile, one active topology scope and one target group. A group may contain more than one runtime config when the manifest explicitly enables runtime bundling. `corpus_cells.csv` is the dimension table for the generated corpus cells. Run the generated `sweeps/*.yml` files through `master-regimes-infra`.
