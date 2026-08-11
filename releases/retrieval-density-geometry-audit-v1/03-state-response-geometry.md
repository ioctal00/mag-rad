# Analiza 3: geometrija fizičkog stanja i geometrija odziva

## Pitanje

Da li veća udaljenost početnih fizičkih stanja u P64→6 prati veću udaljenost vektora stvarno izmjerenih dobitaka tri intervencije?

## Metrike

`raw` je euklidska udaljenost tri log2 dobitka. `centered` prije poređenja oduzima prosječni dobitak svakog slučaja i zato naglašava relativni profil akcija. `action_rank` poredi samo njihov poredak. Posljednje dvije metrike su važnije za pitanje izbora intervencije od zajedničkog nivoa ubrzanja.

## Korelacije

| Parovi | Metrika odziva | n | Spearman rho | Naivni p |
| --- | --- | --- | --- | --- |
| all | response_distance_raw | 8515 | 0.003 | 0.779 |
| all | response_distance_centered | 8515 | 0.003 | 0.799 |
| all | response_rank_distance | 8515 | 0.004 | 0.697 |
| different_query_id | response_distance_raw | 8275 | -0.040 | 0.000 |
| different_query_id | response_distance_centered | 8275 | -0.040 | 0.000 |
| different_query_id | response_rank_distance | 8275 | -0.018 | 0.098 |
| same_query_id | response_distance_raw | 240 | 0.370 | 0.000 |
| same_query_id | response_distance_centered | 240 | 0.351 | 0.000 |
| same_query_id | response_rank_distance | 240 | 0.006 | 0.931 |
| confirmatory_vs_all_prior | response_distance_raw | 1740 | -0.130 | 0.000 |
| confirmatory_vs_all_prior | response_distance_centered | 1740 | -0.127 | 0.000 |
| confirmatory_vs_all_prior | response_rank_distance | 1740 | -0.035 | 0.149 |
| confirmatory_vs_topology | response_distance_raw | 675 | -0.159 | 0.000 |
| confirmatory_vs_topology | response_distance_centered | 675 | -0.155 | 0.000 |
| confirmatory_vs_topology | response_rank_distance | 675 | -0.010 | 0.789 |
| confirmatory_vs_confirmatory | response_distance_raw | 105 | 0.289 | 0.003 |
| confirmatory_vs_confirmatory | response_distance_centered | 105 | 0.247 | 0.011 |
| confirmatory_vs_confirmatory | response_rank_distance | 105 | 0.206 | 0.035 |

Naivni p tretira svih 8515 parova kao nezavisne i prikazan je samo radi audita. Primarni test je 10.000 permutacija cijelih response vektora, odvojeno unutar svakog od četiri eksperimentalna skupa:

| Metrika | Spearman rho | Stratifikovani permutacijski p | Permutacije |
| --- | --- | --- | --- |
| raw | 0.003 | 0.8993 | 10000 |
| centered | 0.003 | 0.9074 | 10000 |
| action_rank | 0.004 | 0.8930 | 10000 |

## Kvintili udaljenosti stanja

| pair_subset | state_distance_bin | pair_count | state_distance_min | state_distance_median | state_distance_max | response_distance_raw_median | response_distance_centered_median | response_rank_distance_median | same_winner_probability |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | 1 | 1703 | 0.027 | 1.787 | 3.068 | 1.684 | 1.248 | 0.000 | 0.717 |
| all | 2 | 1703 | 3.071 | 5.164 | 6.334 | 2.619 | 2.056 | 1.414 | 0.342 |
| all | 3 | 1703 | 6.336 | 8.115 | 8.770 | 2.319 | 1.771 | 1.414 | 0.462 |
| all | 4 | 1703 | 8.771 | 10.389 | 13.425 | 2.100 | 1.673 | 1.414 | 0.624 |
| all | 5 | 1703 | 13.425 | 14.767 | 23.385 | 1.904 | 1.433 | 1.414 | 0.516 |
| different_query_id | 1 | 1655 | 0.174 | 1.929 | 3.395 | 1.812 | 1.362 | 0.000 | 0.678 |
| different_query_id | 2 | 1655 | 3.398 | 5.313 | 6.395 | 2.704 | 2.080 | 1.414 | 0.338 |
| different_query_id | 3 | 1655 | 6.396 | 8.217 | 8.802 | 2.368 | 1.803 | 1.414 | 0.435 |
| different_query_id | 4 | 1655 | 8.802 | 10.443 | 13.501 | 2.084 | 1.647 | 0.000 | 0.636 |
| different_query_id | 5 | 1655 | 13.502 | 14.758 | 23.385 | 1.927 | 1.466 | 1.414 | 0.506 |
| confirmatory_vs_all_prior | 1 | 348 | 0.383 | 4.532 | 5.451 | 1.983 | 1.514 | 0.000 | 0.603 |
| confirmatory_vs_all_prior | 2 | 348 | 5.458 | 5.949 | 6.300 | 2.086 | 1.753 | 1.414 | 0.414 |
| confirmatory_vs_all_prior | 3 | 348 | 6.301 | 6.485 | 6.964 | 2.422 | 1.700 | 1.414 | 0.494 |
| confirmatory_vs_all_prior | 4 | 348 | 6.973 | 14.249 | 14.529 | 1.716 | 1.194 | 0.000 | 0.580 |
| confirmatory_vs_all_prior | 5 | 348 | 14.531 | 14.700 | 15.067 | 1.615 | 1.360 | 1.414 | 0.457 |

## Slaganje najbližeg susjeda

| scope | targets | agreement | median_distance |
| --- | --- | --- | --- |
| svi raniji | 15 | 0.467 | 0.829 |
| drugi potvrdni | 15 | 0.733 | 0.339 |
| završni DBA | 15 | 0.533 | 5.081 |
| razvojni | 15 | 0.533 | 5.005 |
| topology | 15 | 0.467 | 0.829 |

## Zaključak

Na nivou svih stanja nije opažena mjerljiva monotona veza: za centrirani profil odziva rho iznosi 0.003, a za sam poredak akcija 0.004. Stratifikovani permutacijski p za centrirani profil iznosi 0.9074. Udio parova sa istim pobjednikom pada sa 0.717 u najbližem na 0.516 u najudaljenijem kvintilu. Taj pooled obrazac uključuje ponovljene identitete upita. Za sve parove između potvrdnog i ranijih skupova korelacija udaljenosti poretka iznosi samo -0.035. P64→6 zato nije potpuno nevezan za ponovljena lokalna stanja, ali njegova geometrija nije usmjerena na odziv intervencije dovoljno da podrži robustan cross-query izbor akcije. Ovaj audit ne pretvara 131 stanje u dokaz univerzalne neprenosivosti.
