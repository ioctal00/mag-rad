# Analiza 2: konzistentnost pobjednika među fizičkim susjedima

## Pitanje

Kada su dva početna stanja bliska u zamrznutom P64→6 prostoru, koliko često imaju istu najbolju intervenciju?

## Obuhvat

Analiza obuhvata svih 8515 neuređenih parova među 131 kompletnim stanjima. Ona pripadaju samo 31 deklarisanoj logičkoj grupi. Završni DBA i topology panel ponavljaju q01–q15, pa su rezultati posebno prikazani za iste i različite identitete upita. Time se sprečava da ponavljanja istog SQL-a lažno izgledaju kao cross-query generalizacija.

Raspodjela stvarnih pobjednika:

| Skup | Pobjednik | Broj |
| --- | --- | --- |
| potvrdni | mitigate_remote_path_bundle | 8 |
| potvrdni | regional_topk_candidates | 7 |
| završni DBA | mitigate_remote_path_bundle | 31 |
| završni DBA | regional_topk_candidates | 14 |
| razvojni | mitigate_remote_path_bundle | 17 |
| razvojni | regional_topk_candidates | 9 |
| topology | mitigate_remote_path_bundle | 27 |
| topology | regional_topk_candidates | 18 |

Nijedan slučaj nema `increase_gac_work_mem` kao pobjednika. Zato ova analiza provjerava razdvajanje regionalne Top-K i udaljene intervencije, a ne punu troklasnu odluku.

## Kumulativna konzistentnost

| Radijus | Vrijednost | Parovi | P(isti pobjednik) | 95% donja | 95% gornja | Osnova | Razlika |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pooled_q01 | 0.570 | 86 | 0.919 | 0.841 | 0.960 | 0.532 | 0.386 |
| pooled_q05 | 1.334 | 426 | 0.775 | 0.733 | 0.812 | 0.532 | 0.243 |
| pooled_q10 | 1.787 | 852 | 0.724 | 0.693 | 0.753 | 0.532 | 0.192 |
| pooled_q20 | 3.071 | 1703 | 0.717 | 0.695 | 0.738 | 0.532 | 0.185 |
| frozen_P99 | 1.953 | 995 | 0.721 | 0.692 | 0.748 | 0.532 | 0.188 |

Osnova je bezuslovni udio jednakih pobjednika u prikazanom skupu parova. Pozitivna razlika iznad te osnove znači da uži radijus nosi dodatni signal. Wilsonov interval opisuje nesigurnost udjela, ali parovi nisu potpuno nezavisni jer isti slučaj učestvuje u više parova.

Na zamrznutoj P99 granici rezultat po vrsti para je:

| Skup parova | Parovi unutar P99 | P(isti pobjednik) | Osnova | Razlika |
| --- | --- | --- | --- | --- |
| different_query_id | 852 | 0.674 | 0.519 | 0.155 |
| same_query_id | 143 | 1.000 | 1.000 | 0.000 |
| confirmatory_vs_all_prior | 81 | 0.519 | 0.510 | 0.009 |
| confirmatory_vs_reference | 0 |  | 0.510 |  |
| confirmatory_vs_final_dba | 0 |  | 0.513 |  |
| confirmatory_vs_topology | 81 | 0.519 | 0.507 | 0.012 |
| confirmatory_vs_confirmatory | 94 | 0.479 | 0.467 | 0.012 |

## Najbliži susjed

| Skup susjeda | Ciljevi | Udio istog pobjednika | Medijalna udaljenost |
| --- | --- | --- | --- |
| svi drugi slučajevi | 131 | 0.931 | 0.482 |
| svi raniji za potvrdni cilj | 15 | 0.467 | 0.829 |
| potvrdni među potvrdnim | 15 | 0.733 | 0.339 |
| završni DBA za potvrdni cilj | 15 | 0.533 | 5.081 |
| razvojni za potvrdni cilj | 15 | 0.533 | 5.005 |
| topology za potvrdni cilj | 15 | 0.467 | 0.829 |

## Zaključak

Najbliži potvrdni susjed iz istog novog kohorta dijeli pobjednika u 0.733 slučajeva. Najbliži razvojni susjed to čini u samo 0.533 slučajeva, uz medijalnu udaljenost 5.005. Kada se uključe svi raniji paneli, najbliži susjed dijeli pobjednika u 0.467 slučajeva, a 81 par između potvrdnog i svih ranijih panela ulazi u P99. Topology panel zato rješava fizičku nepokrivenost, ali sama dostupnost bliskih stanja još ne garantuje isti pobjednik. Pooled skup pokazuje lokalno slaganje, uglavnom zbog ponovljenih i kontrolisano srodnih stanja. U ciljnom cross-query presjeku P99 donosi samo 0,009 iznad bezuslovne osnove. Upotrebljivost susjeda zato zavisi od porijekla i sastava memorije.
