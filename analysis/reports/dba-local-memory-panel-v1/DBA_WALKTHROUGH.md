# DBA walkthrough: kako lokalna memorija sazrijeva

Ovaj prikaz koristi samo informacije dostupne prije odluke u datoj epizodi. Nakon sto se stvarni ishodi tri poznate akcije izmjere, epizoda se dodaje u memoriju. Dobitak `g` je `log2(T_before / T_after)`, pa `g=1` znaci priblizno dvostruko ubrzanje. Prazna `predicted_action` znaci namjernu apstinenciju.

## Potpuni cold start

Prva epizoda nema historiju, druga ima samo jedan raniji slucaj, a druga pojava istog upita prvi put prelazi minimalni prag od dvije historijske epizode.

| episode_order | query_id | query_occurrence | same_query_history_count_before | nearest_distance | decision_status | candidate_action | predicted_action | actual_best_action | regret_log2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | q01_event_value_desc | 1 | 0 |  | cold_start_abstention |  |  | mitigate_remote_path_bundle |  |
| 2 | q02_event_value_asc | 1 | 0 | 1.503 | provisional_local_evidence | mitigate_remote_path_bundle |  | mitigate_remote_path_bundle |  |
| 3 | q02_event_value_asc | 2 | 1 | 0.732 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | 0.000 |

## Pet uzastopnih pojava novog N=2 upita

`q05_event_deviation` je koristan primjer zato sto se najbolja akcija razlikuje od ranijih raw-event upita. Sistem prvo apstinira, zatim uci iz vlastitih ishoda i mijenja preporuku kada isti lokalni obrazac postane dovoljno zastupljen.

### Odluka prije svake epizode

| query_occurrence | same_query_history_count_before | nearest_distance | decision_status | candidate_action | predicted_action | actual_best_action | regret_log2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 2.897 | outside_reference_coverage | mitigate_remote_path_bundle |  | regional_topk_candidates |  |
| 2 | 1 | 1.162 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | regional_topk_candidates | 0.339 |
| 3 | 2 | 0.211 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | regional_topk_candidates | 0.475 |
| 4 | 3 | 0.121 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | 0.000 |
| 5 | 4 | 0.179 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | 0.000 |

### Predvidjeni i naknadno izmjereni dobici

| query_occurrence | predicted_gain\_\_increase_gac_work_mem | actual_gain\_\_increase_gac_work_mem | predicted_gain\_\_regional_topk_candidates | actual_gain\_\_regional_topk_candidates | predicted_gain\_\_mitigate_remote_path_bundle | actual_gain\_\_mitigate_remote_path_bundle |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.010 | -0.219 | 0.033 | 1.616 | 3.093 | 1.225 |
| 2 | -0.074 | 0.018 | 0.618 | 1.529 | 2.550 | 1.190 |
| 3 | -0.017 | -0.032 | 1.297 | 1.523 | 1.543 | 1.047 |
| 4 | -0.009 | 0.049 | 1.446 | 1.629 | 1.282 | 1.175 |
| 5 | -0.021 | 0.106 | 1.504 | 1.702 | 1.189 | 1.190 |

### Fizicki dokaz pocetnog izvrsenja

| query_occurrence | baseline_elapsed_seconds | evidence_gac_fanin_rows | evidence_gac_temp_blocks | evidence_remote_bytes | evidence_remote_boundary_wait_ms | evidence_remote_rtt_ms | evidence_cpu_busy_max_pct |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2.038 | 128605.000 | 910.000 | 9259560.000 | 1257.719 | 5.482 | 19.737 |
| 2 | 2.059 | 128605.000 | 910.000 | 9259560.000 | 1265.010 | 5.482 | 19.457 |
| 3 | 2.038 | 128605.000 | 910.000 | 9259560.000 | 1264.069 | 5.463 | 19.383 |
| 4 | 2.102 | 128605.000 | 910.000 | 9259560.000 | 1253.977 | 5.458 | 19.920 |
| 5 | 2.129 | 128605.000 | 910.000 | 9259560.000 | 1277.453 | 5.455 | 21.525 |

## Isti upit kada DBA vec ima lokalnu referentnu memoriju

Raniji GAC Top-K panel omogucava ispravnu preporuku od prve nove pojave. Kako se dodaju vlastite epizode, najblizi susjedi postaju prethodna izvrsenja istog upita i procijenjeni dobici se priblizavaju izmjerenim vrijednostima.

| query_occurrence | same_query_history_count_before | nearest_distance | decision_status | candidate_action | predicted_action | actual_best_action | regret_log2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 1.203 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | 0.000 |
| 2 | 1 | 0.795 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | 0.000 |
| 3 | 2 | 0.211 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | 0.000 |
| 4 | 3 | 0.121 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | 0.000 |
| 5 | 4 | 0.179 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | 0.000 |

## Prelazak sa N=2 na N=3

Prva N=3 epizoda je daleko izvan N=2 referentne pokrivenosti, pa sistem ne daje preporuku iako prikazuje kandidata. Nakon sto se taj ishod doda u memoriju, druga pojava istog upita postaje lokalno pokrivena.

| query_occurrence | same_query_history_count_before | nearest_distance | decision_status | candidate_action | predicted_action | actual_best_action | regret_log2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 8.423 | outside_reference_coverage | regional_topk_candidates |  | mitigate_remote_path_bundle |  |
| 2 | 1 | 1.109 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | 0.000 |

## Kako ovo pomaze DBA-u

- Sistem ne tvrdi da poznaje univerzalno najbolju PostgreSQL optimizaciju.
- Prikazuje najblize ranije slucajeve i stvarne ishode poznatih akcija.
- Novi ili topoloski udaljen slucaj zadrzava fizicki dokaz, ali bez preporuke.
- Ponavljanjem i mjerenjem lokalna memorija moze promijeniti raniji pogresan rang.
- `episodes/*.json` cuva pet susjeda, njihove udaljenosti i sve izmjerene ishode.
