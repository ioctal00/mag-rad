# Offline provjere lokalne memorije

## Pitanja

1. Moze li obicno pamcenje identicnog normalizovanog SQL-a objasniti rezultat?
2. Prenosi li kNN iskustvo kada su susjedi istog normalizovanog SQL-a zabranjeni?
3. Sta sistem zna pri prvom susretu sa svakim od 15 SQL oblika?

Sve odluke koriste samo epizode dostupne prije posmatrane epizode. Nije izveden novi infrastrukturni run.

## Ukupni rezultat

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

Exact-query memorija je namjerno stroga: prije prve epizode identicnog normalizovanog SQL-a apstinira, a zatim koristi medijanu njegovih ranijih izmjerenih ishoda po akciji. Cross-query kNN iz svakog susjedstva uklanja sva ranija izvrsenja istog normalizovanog SQL-a.

`hierarchical_cold_start` i `hierarchical_warm_start` predstavljaju stvarni operativni algoritam: poznat normalizovani SQL ide kroz direktnu memoriju, a nepoznat SQL kroz cross-query fizicku slicnost i provjeru pokrivenosti.

## Samo prvo pojavljivanje SQL oblika

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

Ovaj presjek ne moze imati korist od ranijeg izvrsavanja istog SQL-a. Zato je primarna provjera prenosa fizicke reprezentacije izmedju razlicitih upita.

## Upareno poredjenje na istim prvim pojavama

| evaluation_scope | method | episode_count | top1_correct_count | top1_accuracy | mean_regret_log2 | fixed_action |
| --- | --- | --- | --- | --- | --- | --- |
| matched_warm_first_occurrences | static_action_median | 14 | 8 | 0.571 | 0.416 | mitigate_remote_path_bundle |
| matched_warm_first_occurrences | knn_warm_start_excluding_same_query | 14 | 12 | 0.857 | 0.044 |  |

Warm-start kNN i staticka akcija ovdje se porede samo na istih 14 epizoda koje je kNN pokrio. kNN je bio jedini tacan u 4 slucaja, staticka akcija ni u jednom, a prosjecno smanjenje propustenog dobitka iznosilo je 0.372 na logaritamskoj skali. Ovo je deskriptivna provjera namjerno odabranog panela, a ne populacijski interval pouzdanosti.

## Uloga tri akcije

| mitigation_action | episode_count | median_log2_gain | best_action_count | best_action_share |
| --- | --- | --- | --- | --- |
| increase_gac_work_mem | 45 | 0.012 | 0 | 0.000 |
| regional_topk_candidates | 45 | 0.741 | 14 | 0.311 |
| mitigate_remote_path_bundle | 45 | 2.385 | 31 | 0.689 |

`increase_gac_work_mem` je negativna kontrola, a ne treca ravnopravno uspjesna akcija. Panel zato prvenstveno provjerava razlikovanje remote mitigacije i regionalnog Top-K rewritea uz odbacivanje neproduktivne memorijske akcije.

## Granice tumacenja

- Savrsen exact-query rezultat vrijedi samo nakon prvog izmjerenog ishoda istog normalizovanog SQL-a i predstavlja memoizaciju lokalnog iskustva.
- Cross-query rezultat testira prenos iz drugih SQL oblika, ali samo unutar posmatranog GAC Top-K panela i tri unaprijed poznate akcije.
- N=3 epizode dolaze kasnije i koriste druge SQL oblike. Zato ovaj eksperiment pokazuje apstinenciju i naknadnu lokalnu adaptaciju, a ne izolovanu kauzalnu generalizaciju sa N=2 na N=3.
