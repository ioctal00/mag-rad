# Pressure raw v1 - autoritativni audit mitigacijskih akcija

## Ugovor i gate

- Kontrafaktualna jedinica: `418` parova.
- Strogo rezultatski ekvivalentni parovi: `418`.
- Parovi razrijeseni typed correctness recovery provjerom: `83`.
- Nerazrijeseni review parovi sa istim brojem redova i razlicitim hashom: `0`.
- Target je medijanski end-to-end GAC gain kroz tri ponavljanja: `log2(T_stressed / T_mitigated)`.
- Scope gate: `GO`.
- Fatalne nepravilnosti: `nema`.

Pet ranijih pressure osa tretiraju se kao domene dokaza. Modelski targeti se vezuju za eksplicitne mitigacijske akcije ili unaprijed definisane operativne politike, ne za pretpostavljene fizicke uzroke.

## Akcije

| mitigation_action | intervention_role | pair_count | strict_pair_count | stressed_template_count | dataset_count | median_speedup | global_gain_signal | model_readiness |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| disperse_hot_shards | positive_case | 49 | 49 | 4 | 7 | 0.995 | weak_or_inconsistent_global_gain | candidate_null_result_test |
| increase_fetch_size | calibration | 8 | 8 | 4 | 2 | 1.450 | strong_positive_global_gain | calibration_only |
| increase_gac_work_mem | positive_case | 15 | 15 | 1 | 3 | 1.073 | moderate_positive_global_gain | limited_gain_model |
| increase_regional_work_mem | positive_case | 54 | 54 | 1 | 3 | 1.042 | weak_or_inconsistent_global_gain | limited_gain_model |
| mitigate_remote_path_bundle | calibration | 6 | 6 | 1 | 3 | 18.909 | strong_positive_global_gain | limited_gain_model |
| mitigate_remote_path_bundle | positive_case | 24 | 24 | 4 | 3 | 22.275 | strong_positive_global_gain | limited_gain_model |
| regional_join_pushdown | positive_case | 15 | 15 | 1 | 3 | 4.335 | strong_positive_global_gain | limited_gain_model |
| regional_partial_aggregation | positive_case | 15 | 15 | 1 | 3 | 1.585 | strong_positive_global_gain | limited_gain_model |
| regional_prededuplication | positive_case | 15 | 15 | 1 | 3 | 1.913 | strong_positive_global_gain | limited_gain_model |
| regional_topk_candidates | positive_case | 15 | 15 | 1 | 3 | 2.954 | strong_positive_global_gain | limited_gain_model |
| remove_added_delay | calibration | 8 | 8 | 4 | 2 | 14.683 | strong_positive_global_gain | calibration_only |
| remove_bandwidth_limit | calibration | 8 | 8 | 4 | 2 | 6.466 | strong_positive_global_gain | calibration_only |
| use_colocated_distribution | positive_case | 75 | 75 | 4 | 6 | 32.460 | strong_positive_global_gain | candidate_grouped_gain_model |

## Operativne politike

| policy_id | intervention_role | pair_count | strict_pair_count | action_count | stressed_template_count | dataset_count | median_speedup | action_template_confounded | model_readiness |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| gac_memory | positive_case | 15 | 15 | 1 | 1 | 3 | 1.073 | False | limited_gain_model |
| gac_regional_reduction | positive_case | 60 | 60 | 4 | 4 | 3 | 2.591 | True | candidate_grouped_gain_model |
| hot_shard_placement | positive_case | 49 | 49 | 1 | 4 | 7 | 0.995 | False | candidate_null_result_test |
| regional_memory | positive_case | 54 | 54 | 1 | 1 | 3 | 1.042 | False | limited_gain_model |
| remote_transport_bundle | calibration | 6 | 6 | 1 | 1 | 3 | 18.909 | False | limited_gain_model |
| remote_transport_bundle | positive_case | 24 | 24 | 1 | 4 | 3 | 22.275 | False | limited_gain_model |
| remote_transport_calibration | calibration | 24 | 24 | 3 | 4 | 2 | 4.109 | False | calibration_only |
| repartition_colocation | positive_case | 75 | 75 | 1 | 4 | 6 | 32.460 | False | candidate_grouped_gain_model |

`action_template_confounded=true` znaci da je svaka akcija u posmatranoj politici vezana za vlastiti stressed SQL template. Takav skup moze evaluirati vrijednost postojecih action-selection pravila, ali ne dokazuje action-specific prenos na nevidjeni SQL oblik.

## Grupisani holdouti

| entity_id | intervention_role | holdout_type | group_count | minimum_pair_count | strict_group_count | holdout_status |
| --- | --- | --- | --- | --- | --- | --- |
| gac_memory | positive_case | leave_stressed_template_out | 1 | 15 | 1 | not_feasible |
| gac_memory | positive_case | leave_dataset_out | 3 | 5 | 3 | feasible_strict |
| gac_regional_reduction | positive_case | leave_stressed_template_out | 4 | 15 | 4 | structurally_feasible_action_confounded |
| gac_regional_reduction | positive_case | leave_dataset_out | 3 | 20 | 3 | feasible_strict |
| hot_shard_placement | positive_case | leave_stressed_template_out | 4 | 7 | 4 | feasible_strict |
| hot_shard_placement | positive_case | leave_dataset_out | 7 | 7 | 7 | feasible_strict |
| regional_memory | positive_case | leave_stressed_template_out | 1 | 54 | 1 | not_feasible |
| regional_memory | positive_case | leave_dataset_out | 3 | 18 | 3 | feasible_strict |
| remote_transport_bundle | calibration | leave_stressed_template_out | 1 | 6 | 1 | not_feasible |
| remote_transport_bundle | calibration | leave_dataset_out | 3 | 2 | 3 | feasible_strict |
| remote_transport_bundle | positive_case | leave_stressed_template_out | 4 | 6 | 4 | feasible_strict |
| remote_transport_bundle | positive_case | leave_dataset_out | 3 | 8 | 3 | feasible_strict |
| remote_transport_calibration | calibration | leave_stressed_template_out | 4 | 6 | 4 | feasible_strict |
| remote_transport_calibration | calibration | leave_dataset_out | 2 | 12 | 2 | not_feasible |
| repartition_colocation | positive_case | leave_stressed_template_out | 4 | 18 | 4 | feasible_strict |
| repartition_colocation | positive_case | leave_dataset_out | 6 | 12 | 6 | feasible_strict |

Holdout status opisuje samo strukturnu izvodljivost podjele. Ne predstavlja rezultat modela. Ponavljanja, oba clana para i varijante istog scenarija moraju ostati u istom foldu.

## Autoritativna odluka

1. `use_colocated_distribution` ima najjaci action-specific skup za grouped gain model.
2. GAC regionalni rewrite ima dovoljno parova tek kao politika od cetiri akcije, ali akcija i stressed template su konfendirani.
3. Remote bundle ima jak target i svi raniji review parovi sada prolaze typed correctness gate. Fetch, delay i bandwidth blokovi ostaju kalibracijski.
4. `disperse_hot_shards` i `increase_regional_work_mem` imaju slab globalni gain. Njih treba evaluirati protiv null baselinea, bez obecanja pozitivnog modela.
5. Individualni GAC rewrite regresori i GAC memory regresor nemaju dovoljnu stressed-template raznovrsnost za opstu leave-template-out tvrdnju.

## Izlazi

- `mitigation_pair_audit.csv`
- `mitigation_action_summary.csv`
- `mitigation_policy_summary.csv`
- `configuration_transition_summary.csv`
- `holdout_feasibility.csv`
- `learning_curve_checkpoints.csv`
- `mitigation_gain_by_action.png`
- `summary.json`
