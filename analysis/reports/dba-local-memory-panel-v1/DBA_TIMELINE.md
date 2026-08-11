# DBA prikaz lokalne intervencijske memorije

Panel sadrzi 15 novih SQL oblika i 45 vremenski uredjenih intervencijskih epizoda. Jedna epizoda obuhvata pocetno izvrsenje i tri pojedinacno primijenjene poznate akcije. Procjena se pravi prije nego sto se ishodi te epizode dodaju u memoriju. Nema pristupa buducim epizodama.

## Ugovor prikaza

- `cold_start` pocinje bez ranijih ishoda i eksplicitno apstinira.
- `warm_start` koristi 26 ranijih lokalnih GAC Top-K epizoda kao pocetnu memoriju.
- `exact_query_memory` koristi samo ranije ishode identicnog normalizovanog SQL-a.
- `*_cross_query` kNN varijante izbacuju sva ranija ponavljanja istog normalizovanog SQL hasha, uz `query_id` kao dodatni sigurnosni identitet.
- `hierarchical_*` prvo koristi exact-query memoriju, a za nepoznat SQL koristi odgovarajuci cross-query kNN ili apstinira.
- udaljenost veca od P99 lokalne referentne udaljenosti (1.953) daje status `outside_reference_coverage`.
- `candidate_action` prikazuje najvisi trenutni skor i kada dokaz jos nije dovoljan.
- `predicted_action` je stvarna preporuka i ostaje prazna dok status nije `available`.
- izlaz rangira samo tri ranije poznate akcije i ne generise novu optimizaciju.

## Ukupni rezultat

| memory_mode | region_count | episode_count | prediction_count | candidate_count | available_count | outside_coverage_count | top1_accuracy | mean_regret_log2 | candidate_top1_accuracy | candidate_mean_regret_log2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cold_start | 2 | 21 | 18 | 20 | 18 | 1 | 0.889 | 0.045 | 0.850 | 0.060 |
| cold_start | 3 | 24 | 23 | 24 | 23 | 1 | 0.870 | 0.038 | 0.833 | 0.094 |
| cold_start_cross_query | 2 | 21 | 12 | 20 | 12 | 6 | 1.000 | 0.000 | 0.750 | 0.109 |
| cold_start_cross_query | 3 | 24 | 20 | 24 | 20 | 4 | 0.850 | 0.044 | 0.708 | 0.249 |
| exact_query_memory | 2 | 21 | 13 | 13 | 13 | 0 | 1.000 | 0.000 | 1.000 | 0.000 |
| exact_query_memory | 3 | 24 | 17 | 17 | 17 | 0 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_cold_start | 2 | 21 | 18 | 20 | 18 | 1 | 1.000 | 0.000 | 0.950 | 0.020 |
| hierarchical_cold_start | 3 | 24 | 23 | 24 | 23 | 1 | 0.913 | 0.027 | 0.875 | 0.083 |
| hierarchical_warm_start | 2 | 21 | 21 | 21 | 21 | 0 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_warm_start | 3 | 24 | 23 | 24 | 23 | 1 | 0.913 | 0.027 | 0.875 | 0.083 |
| warm_start | 2 | 21 | 21 | 21 | 21 | 0 | 1.000 | 0.000 | 1.000 | 0.000 |
| warm_start | 3 | 24 | 23 | 24 | 23 | 1 | 0.870 | 0.038 | 0.833 | 0.094 |
| warm_start_cross_query | 2 | 21 | 21 | 21 | 21 | 0 | 1.000 | 0.000 | 1.000 | 0.000 |
| warm_start_cross_query | 3 | 24 | 20 | 24 | 20 | 4 | 0.850 | 0.044 | 0.708 | 0.249 |

## Poredjenje sa statickim poretkom akcija

| method | episode_count | recommendation_count | coverage | top1_accuracy | mean_regret_log2 | fixed_action |
| --- | --- | --- | --- | --- | --- | --- |
| static_action_median | 45 | 45 | 1.000 | 0.689 | 0.349 | mitigate_remote_path_bundle |
| knn_cold_start | 45 | 41 | 0.911 | 0.878 | 0.041 |  |
| knn_cold_start_excluding_same_query | 45 | 32 | 0.711 | 0.906 | 0.027 |  |
| exact_query_memory | 45 | 30 | 0.667 | 1.000 | 0.000 |  |
| hierarchical_cold_start | 45 | 41 | 0.911 | 0.951 | 0.015 |  |
| hierarchical_warm_start | 45 | 44 | 0.978 | 0.955 | 0.014 |  |
| knn_warm_start | 45 | 44 | 0.978 | 0.932 | 0.020 |  |
| knn_warm_start_excluding_same_query | 45 | 41 | 0.911 | 0.927 | 0.021 |  |

Staticki baseline uvijek bira akciju sa najvecim medijanom u ranijem lokalnom panelu. kNN koristi iste historijske ishode, ali odluku uslovljava fizickom slicnoscu trenutnog post-execution stanja i apstinira izvan pokrivenosti.

## Prvo pojavljivanje svakog od 15 SQL oblika

| evaluation_scope | method | episode_count | recommendation_count | coverage | top1_accuracy | mean_regret_log2 | fixed_action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| first_occurrence_per_query | static_action_median | 15 | 15 | 1.000 | 0.600 | 0.389 | mitigate_remote_path_bundle |
| first_occurrence_per_query | knn_cold_start | 15 | 11 | 0.733 | 0.818 | 0.056 |  |
| first_occurrence_per_query | knn_cold_start_excluding_same_query | 15 | 11 | 0.733 | 0.818 | 0.056 |  |
| first_occurrence_per_query | exact_query_memory | 15 | 0 | 0.000 |  |  |  |
| first_occurrence_per_query | hierarchical_cold_start | 15 | 11 | 0.733 | 0.818 | 0.056 |  |
| first_occurrence_per_query | hierarchical_warm_start | 15 | 14 | 0.933 | 0.857 | 0.044 |  |
| first_occurrence_per_query | knn_warm_start | 15 | 14 | 0.933 | 0.857 | 0.044 |  |
| first_occurrence_per_query | knn_warm_start_excluding_same_query | 15 | 14 | 0.933 | 0.857 | 0.044 |  |

Ovaj presjek uklanja korist od ranijeg izvrsavanja istog upita. Exact-query memorija po definiciji tada apstinira, dok cross-query kNN moze koristiti samo druge SQL oblike. N=3 upiti dolaze kasnije u vremenskom redoslijedu i koriste druge SQL oblike, pa ovaj panel ne daje cist kauzalni N=2/N=3 kontrast.

`increase_gac_work_mem` je namjerno zadrzan kao negativna kontrola. Njegov slab izmjereni dobitak provjerava hoce li metoda bez fizickog opravdanja preporucivati akciju samo zato sto je dostupna u skupu kandidata.

## Promjena od prvog do petog susreta sa istim upitom

| memory_mode | query_occurrence | query_count | available_count | recommendation_count | top1_accuracy | mean_regret_log2 | candidate_top1_accuracy | candidate_mean_regret_log2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cold_start | 1 | 15 | 11 | 11 | 0.818 | 0.056 | 0.714 | 0.170 |
| cold_start | 2 | 12 | 12 | 12 | 0.833 | 0.050 | 0.833 | 0.050 |
| cold_start | 3 | 9 | 9 | 9 | 0.889 | 0.053 | 0.889 | 0.053 |
| cold_start | 4 | 6 | 6 | 6 | 1.000 | 0.000 | 1.000 | 0.000 |
| cold_start | 5 | 3 | 3 | 3 | 1.000 | 0.000 | 1.000 | 0.000 |
| cold_start_cross_query | 1 | 15 | 11 | 11 | 0.818 | 0.056 | 0.714 | 0.170 |
| cold_start_cross_query | 2 | 12 | 8 | 8 | 0.875 | 0.032 | 0.750 | 0.160 |
| cold_start_cross_query | 3 | 9 | 7 | 7 | 1.000 | 0.000 | 0.778 | 0.173 |
| cold_start_cross_query | 4 | 6 | 4 | 4 | 1.000 | 0.000 | 0.667 | 0.295 |
| cold_start_cross_query | 5 | 3 | 2 | 2 | 1.000 | 0.000 | 0.667 | 0.171 |
| exact_query_memory | 1 | 15 | 0 | 0 |  |  |  |  |
| exact_query_memory | 2 | 12 | 12 | 12 | 1.000 | 0.000 | 1.000 | 0.000 |
| exact_query_memory | 3 | 9 | 9 | 9 | 1.000 | 0.000 | 1.000 | 0.000 |
| exact_query_memory | 4 | 6 | 6 | 6 | 1.000 | 0.000 | 1.000 | 0.000 |
| exact_query_memory | 5 | 3 | 3 | 3 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_cold_start | 1 | 15 | 11 | 11 | 0.818 | 0.056 | 0.714 | 0.170 |
| hierarchical_cold_start | 2 | 12 | 12 | 12 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_cold_start | 3 | 9 | 9 | 9 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_cold_start | 4 | 6 | 6 | 6 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_cold_start | 5 | 3 | 3 | 3 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_warm_start | 1 | 15 | 14 | 14 | 0.857 | 0.044 | 0.800 | 0.133 |
| hierarchical_warm_start | 2 | 12 | 12 | 12 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_warm_start | 3 | 9 | 9 | 9 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_warm_start | 4 | 6 | 6 | 6 | 1.000 | 0.000 | 1.000 | 0.000 |
| hierarchical_warm_start | 5 | 3 | 3 | 3 | 1.000 | 0.000 | 1.000 | 0.000 |
| warm_start | 1 | 15 | 14 | 14 | 0.857 | 0.044 | 0.800 | 0.133 |
| warm_start | 2 | 12 | 12 | 12 | 0.917 | 0.021 | 0.917 | 0.021 |
| warm_start | 3 | 9 | 9 | 9 | 1.000 | 0.000 | 1.000 | 0.000 |
| warm_start | 4 | 6 | 6 | 6 | 1.000 | 0.000 | 1.000 | 0.000 |
| warm_start | 5 | 3 | 3 | 3 | 1.000 | 0.000 | 1.000 | 0.000 |
| warm_start_cross_query | 1 | 15 | 14 | 14 | 0.857 | 0.044 | 0.800 | 0.133 |
| warm_start_cross_query | 2 | 12 | 11 | 11 | 0.909 | 0.023 | 0.833 | 0.132 |
| warm_start_cross_query | 3 | 9 | 8 | 8 | 1.000 | 0.000 | 0.889 | 0.120 |
| warm_start_cross_query | 4 | 6 | 5 | 5 | 1.000 | 0.000 | 0.833 | 0.219 |
| warm_start_cross_query | 5 | 3 | 3 | 3 | 1.000 | 0.000 | 1.000 | 0.000 |

## Ono sto DBA vidi prije i poslije svake epizode

| episode_order | query_id | query_occurrence | region_count | decision_status | candidate_action | predicted_action | actual_best_action | top1_correct | regret_log2 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | q01_event_value_desc | 1 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 2 | q02_event_value_asc | 1 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 3 | q02_event_value_asc | 2 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 4 | q03_event_recent | 1 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 5 | q03_event_recent | 2 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 6 | q03_event_recent | 3 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 7 | q04_event_oldest | 1 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 8 | q04_event_oldest | 2 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 9 | q04_event_oldest | 3 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 10 | q04_event_oldest | 4 | 2 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 11 | q05_event_deviation | 1 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 12 | q05_event_deviation | 2 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 13 | q05_event_deviation | 3 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 14 | q05_event_deviation | 4 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 15 | q05_event_deviation | 5 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 16 | q06_tenant_sum | 1 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 17 | q07_tenant_count | 1 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 18 | q07_tenant_count | 2 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 19 | q08_tenant_avg | 1 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 20 | q08_tenant_avg | 2 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 21 | q08_tenant_avg | 3 | 2 | available | regional_topk_candidates | regional_topk_candidates | regional_topk_candidates | True | 0.000 |
| 22 | q09_tenant_max | 1 | 3 | outside_reference_coverage | regional_topk_candidates |  | mitigate_remote_path_bundle | False |  |
| 23 | q09_tenant_max | 2 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 24 | q09_tenant_max | 3 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 25 | q09_tenant_max | 4 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 26 | q10_tenant_min | 1 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 27 | q10_tenant_min | 2 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 28 | q10_tenant_min | 3 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 29 | q10_tenant_min | 4 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 30 | q10_tenant_min | 5 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 31 | q11_tenant_high_count | 1 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | regional_topk_candidates | False | 0.501 |
| 32 | q12_tenant_user_sum | 1 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | regional_topk_candidates | False | 0.119 |
| 33 | q12_tenant_user_sum | 2 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | regional_topk_candidates | False | 0.258 |
| 34 | q13_tenant_user_count | 1 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 35 | q13_tenant_user_count | 2 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 36 | q13_tenant_user_count | 3 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 37 | q14_tenant_day_sum | 1 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 38 | q14_tenant_day_sum | 2 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 39 | q14_tenant_day_sum | 3 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 40 | q14_tenant_day_sum | 4 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 41 | q15_tenant_day_count | 1 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 42 | q15_tenant_day_count | 2 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 43 | q15_tenant_day_count | 3 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 44 | q15_tenant_day_count | 4 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |
| 45 | q15_tenant_day_count | 5 | 3 | available | mitigate_remote_path_bundle | mitigate_remote_path_bundle | mitigate_remote_path_bundle | True | 0.000 |

Detaljni fizicki dokaz, svih pet susjeda i izmjereni ishod svake akcije nalaze se u `episodes/*.json`. `dba_episode_timeline.csv` je masinski citljiv prikaz istog vremenskog toka.
