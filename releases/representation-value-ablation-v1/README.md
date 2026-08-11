# Offline provjera vrijednosti višeslojne reprezentacije

## Istraživačko pitanje

> Da li višeslojno post-execution fizičko stanje daje bolji cross-query intervencijski transfer od jednostavne strukturne sličnosti SQL-a i jednostavnijih lokalnih pokazatelja?

Eksperiment ne pokreće infrastrukturu i ne mijenja postojeće rezultate. Sve transformacije fitovane su isključivo nad 26 razvojnih stanja. Završnih 45 epizoda koristi se samo za vremenski uređenu evaluaciju.

## Zamrznuta politika

- kNN: `k=5`
- metrika: `euclidean`
- apstinencija: omjer prema razvojnoj P99 udaljenosti, zajednički prag 1,0
- isti `query_id` i isti normalizovani SQL isključeni su iz susjeda
- akcije: `increase_gac_work_mem, regional_topk_candidates, mitigate_remote_path_bundle`

Broj pojavljivanja po SQL-u u stvarnom panelu nije uniformno tri. Raspodjela je 1--5, po tri SQL obrasca za svaki broj pojavljivanja. To ne mijenja dvije predefinisane evaluacije: 15 prvih pojavljivanja i svih 45 epizoda.

## Reprezentacije

1. `sql_structural`: 18 SQL-strukturnih i 7 osnovnih GAC plan pokazatelja, skaliranih samo na razvojnoj memoriji, bez PCA.
2. `coordinator_physical`: standardni rezultat, buffer i coordinator EXPLAIN pokazatelji, bez regiona, worker/task, edge i OS dokaza.
3. `full_multilayer`: neizmijenjeni tok 93 kandidata -> 64 aktivna pokazatelja -> 6 PCA komponenti.

Razvojnih 26 stanja sadrži samo jedan normalizovani SQL oblik. Zbog toga je svih 25 strukturnih koordinata konstantno i razvojni P99 prag `0.0000`. SQL baseline je zato strogi test strukturne kompatibilnosti, a ne dokaz da je na razvojnom skupu naučena bogata SQL geometrija. Konstantne koordinate nisu uklonjene, jer bi to unaprijed onemogućilo opažanje nove strukture u završnom panelu.

Sirovi prag udaljenosti izračunat je zasebno u svakom prostoru samo iz razvojnih stanja. Odluka je u svim reprezentacijama ista: preporuka se izdaje ako je omjer `udaljenost / razvojni P99` najviše 1,0. Time različite jedinice prostora ne dijele proizvoljan numerički prag.

## Prvo pojavljivanje SQL-a

| representation | episode_count | recommendation_count | coverage | correct_decision_count | top1_accuracy | mean_regret_log2 |
| --- | --- | --- | --- | --- | --- | --- |
| coordinator_physical | 15 | 14 | 0.9333 | 11 | 0.7857 | 0.3087 |
| full_multilayer | 15 | 14 | 0.9333 | 12 | 0.8571 | 0.0443 |
| sql_structural | 15 | 9 | 0.6000 | 7 | 0.7778 | 0.1599 |

## Svih 45 epizoda bez istog SQL-a među susjedima

| representation | episode_count | recommendation_count | coverage | correct_decision_count | top1_accuracy | mean_regret_log2 |
| --- | --- | --- | --- | --- | --- | --- |
| coordinator_physical | 45 | 41 | 0.9111 | 27 | 0.6585 | 0.4430 |
| full_multilayer | 45 | 41 | 0.9111 | 38 | 0.9268 | 0.0214 |
| sql_structural | 45 | 33 | 0.7333 | 25 | 0.7576 | 0.1543 |

## Exact-query memorija kao odvojena referenca

| reference_method | evaluation | episode_count | recommendation_count | coverage | correct_decision_count | top1_accuracy | mean_regret_log2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| exact_query_memory | first_occurrence | 15 | 0 | 0.0000 | 0 |  |  |
| exact_query_memory | all_episodes | 45 | 30 | 0.6667 | 30 | 1.0000 | 0.0000 |

Exact-query rezultat nije uključen u poređenje cross-query reprezentacija.

## Intervali i uparene razlike

`bootstrap_intervals.csv` sadrži 95% grupisane bootstrap intervale po `query_id`. `paired_representation_differences.csv` koristi iste resamplirane SQL klastere za upareno poređenje pune reprezentacije sa svakim baselineom. Pozitivna razlika u toj tabeli uvijek favorizuje punu reprezentaciju. Obje tabele koriste po 10000 odnosno 10000 resampliranja.

Na svih 45 epizoda upareni 95% interval ne obuhvata nulu za sljedeće razlike:

| baseline | metric | mean_difference | ci_lower | ci_upper |
| --- | --- | --- | --- | --- |
| sql_structural | coverage | 0.1843 | 0.0392 | 0.3939 |
| coordinator_physical | mean_regret_log2 | 0.4043 | 0.0114 | 0.9380 |

## Provjere protiv leakagea

Status: **PASS**

| check                                                   | passed |
| ------------------------------------------------------- | ------ |
| development_only_fit                                    | True   |
| same_query_neighbors_excluded                           | True   |
| same_normalized_sql_neighbors_excluded                  | True   |
| future_neighbors_excluded                               | True   |
| identical_episode_sets                                  | True   |
| identical_action_outcomes                               | True   |
| abstentions_separate_from_top1_denominator              | True   |
| full_representation_reproduces_existing_frozen_timeline | True   |

## Zaključak

Puna višeslojna reprezentacija daje najbolji kvalitet među izdatim preporukama u obje glavne metrike, uz pokrivenost prikazanu odvojeno. Tačkasta procjena nije sama po sebi dokaz univerzalne nadmoći. Za prva pojavljivanja intervali razlika kvaliteta obuhvataju nulu. Na svih 45 epizoda statistički je najjasnija prednost pune reprezentacije niži regret u odnosu na baseline koji koristi samo koordinator, dok prema SQL baselineu najjasnije raste pokrivenost. Top-1 razlike ostaju pozitivne u tačkastoj procjeni, ali njihovi grupisani bootstrap intervali obuhvataju nulu.

Rezultat govori o cross-query transferu tri poznate akcije u ovom GAC Top-K panelu. Ne dokazuje univerzalnu dijagnozu, izbor proizvoljne PostgreSQL akcije ni prenosivost na neopažene domene.

## Reprodukcija

```bash
make representation-value-ablation
make representation-value-ablation-local-gate
```

Mašinski čitljivi tragovi:

- `episode_results.csv`: odluka svake reprezentacije za svih 45 epizoda
- `representation_summary.csv`: glavne metrike po evaluaciji
- `first_occurrence_results.csv`: 15 prvih pojavljivanja
- `same_query_excluded_results.csv`: svih 45 epizoda
- `neighbor_trace.csv`: odabrani susjedi, udaljenosti i historijski ishodi
- `action_rankings.csv`: procijenjeni i stvarni poredak tri akcije
- `representation_features.csv`: uključeni i isključeni pokazatelji
- `feature_fit_audit.csv`: odluke fitovane samo na razvojnoj memoriji
- `bootstrap_intervals.csv`: grupisani bootstrap intervali
- `leakage_checks.json`: automatske metodološke provjere
- `input_manifest.json`: hash korištenih ulaza

Razvojni fit po reprezentaciji: `{"coordinator_physical": {"dimensions": 6, "states": 26, "threshold": 0.7712676406493916}, "full_multilayer": {"dimensions": 6, "states": 26, "threshold": 1.9533554892194174}, "sql_structural": {"dimensions": 25, "states": 26, "threshold": 0.0}}`.
