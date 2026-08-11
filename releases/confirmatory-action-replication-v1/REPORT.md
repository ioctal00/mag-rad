# Potvrdni panel lokalne intervencijske memorije

Panel sadrzi 15 novih SQL oblika, cetiri uslova i pet ponavljanja po uslovu. Transformacija R3, k=5, euklidska udaljenost i empirical-P99 pravilo nisu refitovani. Sva 300 izvrsenja prosla su kolekcijski i rezultatski ugovor.

## Stabilnost izmjerenih ishoda

- ista akcija pobijedila je u svih pet ponavljanja za 15/15 scenarija;
- prakticno izjednacenih pobjednika: 0/15;
- broj pobjeda: remote putanja 8/15, regionalni Top-K 7/15, GAC work_mem 0/15.

## Zbirni rezultati

| mode | decision_count | recommendation_count | abstention_count | coverage | strict_top1 | tie_aware_top1 | mean_regret_log2 | median_nearest_distance | bootstrap_clusters | coverage_ci_low | coverage_ci_high | strict_top1_ci_low | strict_top1_ci_high | tie_aware_top1_ci_low | tie_aware_top1_ci_high | mean_regret_log2_ci_low | mean_regret_log2_ci_high |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| static_action_median | 15 | 15 | 0 | 1.0000 | 0.5333 | 0.5333 | 0.3894 | 0.0000 | 15 | 1.0000 | 1.0000 | 0.2667 | 0.8000 | 0.2667 | 0.8000 | 0.1215 | 0.7075 |
| frozen_transfer | 15 | 0 | 15 | 0.0000 |  |  |  | 5.0051 | 15 | 0.0000 | 0.0000 |  |  |  |  |  |  |
| prequential_full_feedback | 15 | 14 | 1 | 0.9333 | 0.5714 | 0.5714 | 0.3522 | 0.5687 | 15 | 0.8000 | 1.0000 | 0.3077 | 0.8333 | 0.3077 | 0.8333 | 0.0678 | 0.6825 |
| partial_feedback_round_robin | 15 | 14 | 1 | 0.9333 | 0.5714 | 0.5714 | 0.3037 | 0.5687 | 15 | 0.8000 | 1.0000 | 0.3077 | 0.8462 | 0.3077 | 0.8462 | 0.0701 | 0.5879 |
| partial_feedback_random_seed_11 | 15 | 6 | 9 | 0.4000 | 0.5000 | 0.5000 | 0.4479 | 0.5687 | 15 | 0.1333 | 0.6667 | 0.0000 | 1.0000 | 0.0000 | 1.0000 | 0.0000 | 1.0450 |
| partial_feedback_random_seed_29 | 15 | 13 | 2 | 0.8667 | 0.3846 | 0.3846 | 0.5593 | 0.5687 | 15 | 0.6667 | 1.0000 | 0.1429 | 0.6667 | 0.1429 | 0.6667 | 0.1967 | 0.9637 |
| partial_feedback_random_seed_47 | 15 | 14 | 1 | 0.9333 | 0.6429 | 0.6429 | 0.1869 | 0.5687 | 15 | 0.8000 | 1.0000 | 0.3846 | 0.8667 | 0.3846 | 0.8667 | 0.0325 | 0.3865 |
| partial_feedback_random_seed_71 | 15 | 12 | 3 | 0.8000 | 0.6667 | 0.6667 | 0.1423 | 0.5687 | 15 | 0.6000 | 1.0000 | 0.3846 | 0.9167 | 0.3846 | 0.9167 | 0.0169 | 0.3382 |
| partial_feedback_random_seed_101 | 15 | 12 | 3 | 0.8000 | 0.6667 | 0.6667 | 0.2542 | 0.5687 | 15 | 0.6000 | 1.0000 | 0.3846 | 0.9167 | 0.3846 | 0.9167 | 0.0169 | 0.5781 |

Strogi transfer ne dodaje nijedan ishod novog panela u memoriju. Prequential i partial-feedback replay koriste isti fizicki panel, ali razlicite unaprijed definisane ugovore otkrivanja ishoda.

## Tumacenje

Zamrznuti transfer apstinirao je za 15/15 potpuno novih SQL oblika: njihova fizicka stanja bila su izvan zamrznute P99 granice. Nakon prequentialnog dodavanja lokalnih epizoda pokrivenost je bila 14/15, Top-1 0.571, a srednji regret 0.352 log2. Round-robin partial-feedback replay ostvario je pokrivenost 14/15, Top-1 0.571 i srednji regret 0.304 log2. Staticki action-median baseline imao je Top-1 0.533 i regret 0.389 log2. Lokalna memorija zato je vratila pokrivenost i smanjila regret u round-robin replayu, ali nije dala uvjerljiv dokaz robusno boljeg izbora akcije na ovom panelu.

Zakljucak se odnosi na zamrznuti R3 prostor i tri ispitane akcije. Panel ne izoluje doprinos apsolutnih naspram relativnih pokazatelja.
