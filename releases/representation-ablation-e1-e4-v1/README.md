# Offline ablation reprezentacija kroz E1-E4

## Pitanje

> Da li puna viseslojna post-execution fizicka reprezentacija daje korisniji cross-query intervencijski transfer od SQL-strukturne ili pojednostavljene coordinator fizicke reprezentacije?

Ovaj eksperiment nije pokrenuo nijedan SQL upit. Ponovo koristi 26 razvojnih stanja, 45 epizoda zavrsnog DBA panela i 45 kontrolisanih N2/N3 epizoda. Arhivirani rezultati nisu mijenjani.

## Reprezentacije

- **R1 SQL-strukturna:** 18 obiljezja normalizovanog SQL-a i sedam osnovnih porodica operatora glavnog GAC plana. Ne koristi identifikatore niti runtime action ishode. Svih 25 kandidata ostaje u izlaznom prostoru.
- **R2 coordinator fizicka:** rezultat, wall-clock, bufferi i standardni coordinator `EXPLAIN` pokazatelji. Iskljucuje regionalne planove, worker/task fragmente, edge dokaz, OS telemetriju i viseslojne topoloske odnose. Od 22 kandidata, 15 je aktivno na razvojnoj referenci, pa su reducirani na sest PCA komponenti.
- **R3 puna viseslojna:** neizmijenjeni zamrznuti tok 93 kandidata -> 64 aktivna pokazatelja -> 6 PCA komponenti. Parametri su ucitani iz postojeceg artefakta, bez refita na zavrsnom ili N3 panelu.

## Kalibracija pokrivenosti

Svaka reprezentacija koristi k=5 i euklidsku udaljenost, ali vlastiti empirical P99 prag izracunat samo iz razvojnih stanja:

| representation | fit_state_count | output_dimensions | coverage_quantile | coverage_threshold |
| --- | --- | --- | --- | --- |
| R1_sql_structural | 26 | 25 | 0.9900 | 0.0000 |
| R2_coordinator_physical | 26 | 6 | 0.9900 | 0.7713 |
| R3_full_multilayer | 26 | 6 | 0.9900 | 1.9534 |

R1 prag je nula jer razvojnih 26 stanja sadrzi jedan SQL oblik i sve njegove strukturne koordinate su konstantne. To je stvarno ogranicenje dostupnog kalibracijskog skupa, ne razlog za post-hoc sirenje praga.

## E1-E4

| evaluation | representation | episode_count | recommendation_count | abstention_count | coverage | correct_decision_count | top1_accuracy | mean_regret_log2 | nearest_distance_median |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | R1_sql_structural | 15 | 9 | 6 | 0.6000 | 7 | 0.7778 | 0.1599 | 0.0000 |
| E1 | R2_coordinator_physical | 15 | 14 | 1 | 0.9333 | 11 | 0.7857 | 0.3087 | 0.4886 |
| E1 | R3_full_multilayer | 15 | 14 | 1 | 0.9333 | 12 | 0.8571 | 0.0443 | 1.2030 |
| E2 | R1_sql_structural | 45 | 33 | 12 | 0.7333 | 25 | 0.7576 | 0.1543 | 0.0000 |
| E2 | R2_coordinator_physical | 45 | 41 | 4 | 0.9111 | 27 | 0.6585 | 0.4430 | 0.4766 |
| E2 | R3_full_multilayer | 45 | 41 | 4 | 0.9111 | 38 | 0.9268 | 0.0214 | 1.1617 |
| E3 | R1_sql_structural | 15 | 0 | 15 | 0.0000 | 0 |  |  | 0.1538 |
| E3 | R2_coordinator_physical | 15 | 14 | 1 | 0.9333 | 9 | 0.6429 | 0.4704 | 0.4887 |
| E3 | R3_full_multilayer | 15 | 0 | 15 | 0.0000 | 0 |  |  | 6.6577 |
| E4 | R1_sql_structural | 15 | 14 | 1 | 0.9333 | 8 | 0.5714 | 0.5492 | 0.0000 |
| E4 | R2_coordinator_physical | 15 | 15 | 0 | 1.0000 | 8 | 0.5333 | 0.6885 | 0.4852 |
| E4 | R3_full_multilayer | 15 | 15 | 0 | 1.0000 | 12 | 0.8000 | 0.2307 | 1.3135 |

Na E2 puna reprezentacija postiže Top-1 `0.9268` uz regret `0.0214`. Najbolja tačkasta reprezentacija na E2 je `R3_full_multilayer`, a na E4 `R3_full_multilayer`. Coverage i kvalitet moraju se citati zajedno, jer apstinencije nisu racunate kao pogresne Top-1 preporuke.

Na prvom susretu s novim SQL-om R3 daje preporuku za `14/15` epizoda i ispravno bira prvu akciju u `12` od tih slucajeva. U E3 isti zamrznuti prostor ne prenosi preporuke na N3: medijana udaljenosti `6.6577` veca je od praga `1.9534`, pa R3 apstinira u svih `15` epizoda. R2 u E3 pokriva `14/15`, ali uz Top-1 `0.6429` i regret `0.4704`. Nakon sto je faza A dodana kao ranija N3 memorija, R3 u E4 pokriva svih `15` epizoda uz Top-1 `0.8000`. To razlikuje otkrivanje nepokrivenog fizickog stanja od uspjesnog prijenosa action-response ponasanja.

## Exact i logical memorija

| evaluation | reference_method | episode_count | recommendation_count | coverage | top1_accuracy | mean_regret_log2 |
| --- | --- | --- | --- | --- | --- | --- |
| E1 | exact_context_memory | 15 | 0 | 0.0000 |  |  |
| E1 | logical_query_memory | 15 | 0 | 0.0000 |  |  |
| E2 | exact_context_memory | 45 | 30 | 0.6667 | 1.0000 | 0.0000 |
| E2 | logical_query_memory | 45 | 30 | 0.6667 | 1.0000 | 0.0000 |
| E3 | exact_context_memory | 15 | 0 | 0.0000 |  |  |
| E3 | logical_query_memory | 15 | 15 | 1.0000 | 1.0000 | 0.0000 |
| E4 | exact_context_memory | 15 | 15 | 1.0000 | 1.0000 | 0.0000 |
| E4 | logical_query_memory | 15 | 15 | 1.0000 | 1.0000 | 0.0000 |

Ovi redovi su referentni baselinei i nisu ukljuceni u cross-query poređenje R1-R3.

## Fizicka i action-response udaljenost

| representation | pair_type | pair_count | representation_distance_median | action_response_distance_l2_median | best_action_agreement_share | rank_disagreement_mean | distance_response_spearman |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R1_sql_structural | N2-N2 | 105 | 0.1287 | 2.2992 | 0.4857 | 0.1714 | -0.0236 |
| R1_sql_structural | N2-N3 | 450 | 0.1822 | 2.1501 | 0.5200 | 0.1711 | 0.1310 |
| R1_sql_structural | N3-N3 | 435 | 0.0858 | 2.1596 | 0.5034 | 0.1877 | 0.0617 |
| R2_coordinator_physical | N2-N2 | 105 | 1.1583 | 2.2992 | 0.4857 | 0.1714 | 0.2763 |
| R2_coordinator_physical | N2-N3 | 450 | 1.1191 | 2.1501 | 0.5200 | 0.1711 | 0.3926 |
| R2_coordinator_physical | N3-N3 | 435 | 1.1331 | 2.1596 | 0.5034 | 0.1877 | 0.3460 |
| R3_full_multilayer | N2-N2 | 105 | 12.6709 | 2.2992 | 0.4857 | 0.1714 | 0.1340 |
| R3_full_multilayer | N2-N3 | 450 | 8.7001 | 2.1501 | 0.5200 | 0.1711 | -0.1388 |
| R3_full_multilayer | N3-N3 | 435 | 14.2120 | 2.1596 | 0.5034 | 0.1877 | 0.1178 |

Za iste SQL scenarije preko N2-N3 granice:

| representation | matched_pair_count | physical_distance_median | response_distance_median | best_action_agreement |
| --- | --- | --- | --- | --- |
| R1_sql_structural | 30 | 0.1608 | 0.3439 | 1.0000 |
| R2_coordinator_physical | 30 | 0.0451 | 0.3439 | 1.0000 |
| R3_full_multilayer | 30 | 6.7993 | 0.3439 | 1.0000 |

Spearmanove vrijednosti su eksploratorne. Parovi dijele epizode i zato nisu nezavisna populacijska opazanja. Analiza provjerava geometrijsko slaganje, a ne kauzalnost.

## Grupisani bootstrap

Intervali su dobijeni sa `10000` resampliranja, grupisanih po `query_id`. Pozitivna uparena razlika favorizuje R3. Intervali koji ne obuhvataju nulu su:

| evaluation | baseline | metric | mean_difference | ci_lower | ci_upper |
| --- | --- | --- | --- | --- | --- |
| E1 | R1_sql_structural | coverage | 0.3332 | 0.1333 | 0.6000 |
| E2 | R1_sql_structural | coverage | 0.1841 | 0.0392 | 0.3947 |
| E2 | R2_coordinator_physical | mean_regret_log2 | 0.4135 | 0.0132 | 0.9518 |
| E3 | R2_coordinator_physical | coverage | -0.9328 | -1.0000 | -0.8000 |
| E4 | R2_coordinator_physical | mean_regret_log2 | 0.4569 | 0.0986 | 0.8844 |

## Leakage i reprodukcija

Status: **PASS**

| check                                              | passed |
| -------------------------------------------------- | ------ |
| all_transforms_fit_only_on_development_reference   | True   |
| R3_uses_preexisting_artifact_without_n3_fit        | True   |
| no_same_query_neighbors                            | True   |
| no_same_logical_identity_neighbors                 | True   |
| no_future_final_panel_neighbors                    | True   |
| identical_episode_sets_by_evaluation               | True   |
| identical_action_outcomes_by_evaluation            | True   |
| abstentions_excluded_from_top1_denominator         | True   |
| feature_contract_excludes_identifiers_and_outcomes | True   |
| coverage_thresholds_calibrated_per_representation  | True   |
| R3_reproduces_archived_E2                          | True   |
| R3_reproduces_archived_E3_E4                       | True   |

## Zakljucak

Rezultat se ne tumaci kao univerzalna pobjeda jedne reprezentacije. E1 i E2 direktno mjere cross-query vrijednost dodatnog viseslojnog dokaza, dok E3 i E4 pokazuju da geometrijska osjetljivost na promjenu topologije nije isto sto i promjena optimalnog action-response poretka. R1 i R2 ostaju stvarni baselinei, a ne namjerno oslabljene varijante.

## Otvoreni metodoloski problemi

- Razvojna referenca sadrzi 26 stanja jednog SQL oblika. R1 P99 je zato nula i nije robustno kalibrisan za raznovrsnu SQL-strukturnu memoriju.
- Samo 15 `query_id` grupa ulazi u svaku zavrsnu evaluaciju. Tačkaste Top-1 razlike uglavnom imaju siroke bootstrap intervale i ne dokazuju univerzalnu nadmoc R3.
- Potpuna apstinencija R3 u E3 potvrđuje detekciju nepokrivenog N3 stanja, ali ne daje procjenu kakvu bi preporuku R3 napravio bez coverage pravila.
- Fizicka/action-response korelacija je eksploratorna jer parovi dijele epizode i nisu nezavisna populacijska opazanja.
- Zakljucci vaze za tri poznate GAC Top-K akcije i posmatranu infrastrukturu. Ne dokazuju izbor proizvoljne PostgreSQL akcije niti univerzalnu prenosivost.

## Reprodukcija

```bash
make representation-ablation-e1-e4
make representation-ablation-e1-e4-local-gate
```

Glavni masinski izlazi su `episode_representation_results.csv`, `representation_summary.csv`, `neighbor_trace.csv`, `action_rankings.csv`, `bootstrap_intervals.csv`, `paired_representation_differences.csv`, `physical_action_response_pairs.csv`, `physical_action_response_summary.csv`, `identity_memory_results.csv`, `feature_manifest.csv`, `fit_manifest.json`, `leakage_audit.json` i `input_manifest.json`.
