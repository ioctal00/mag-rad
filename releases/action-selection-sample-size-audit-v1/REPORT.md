# Audit veličine uzorka za izbor intervencije

Ovaj audit ne izvršava SQL. Razdvaja fizička izvršenja od jedinica procjene na kojima se računaju pokrivenost i Top-1.

## Eksperimentalne jedinice

| Blok | Fizička izvršenja | Stanja/odluke | SQL jedinice | Dopuštena upotreba |
| --- | ---: | ---: | --- | --- |
| F19 characterization corpus | 1964 | 1964 | not an action-ranking unit | descriptive FCM characterization for RQ1-RQ4 |
| broad intervention corpus | 2607 | 869 | 30 templates; 13 logical questions | collector, equivalence, physical response, intervention contract |
| development/reference ranking panel | 312 | 26 | 4 templates; 1 logical question | development of P64->6, k, distance, P99 and comparators |
| final temporal DBA panel | 180 | 45 | 15 | temporal first occurrence and repeated-query behavior |
| controlled topology-memory panel | 180 | 45 | 15 | controlled N2/N3 shift and local adaptation |
| confirmatory new-query panel | 300 | 15 | 15 | stability of winners and bounded new-query transfer test |

## Potvrdni panel

| Postupak | Odluke | Preporuke | Tačno | Top-1 | Wilson 95% |
| --- | ---: | ---: | ---: | ---: | --- |
| static_action_median | 15 | 15 | 8 | 0.533 | [0.301, 0.752] |
| frozen_transfer | 15 | 0 | 0 | nije primjenjivo | nije primjenjivo |
| prequential_full_feedback | 15 | 14 | 8 | 0.571 | [0.326, 0.786] |

Top-1 od 0,571 predstavlja 8 tačnih preporuka među 14 izdatih. Statički poredak predstavlja 8 tačnih odluka među svih 15 SQL oblika. Na 14 zajedničkih preporuka oba postupka su bila tačna sedam puta i pogrešna šest puta; vremensko dopunjavanje ispravilo je samo jednu grešku statičkog poretka. Egzaktni dvostrani McNemarov test daje p=1.000.

Pet ponavljanja svakog uslova stabilizuje mjerenje stvarnog pobjednika, ali ne povećava broj SQL jedinica procjene sa 15 na 300. Jedna odluka mijenja Top-1 8/14 za približno 0,071. Zato panel ne procjenjuje univerzalnu tačnost; podržava ograničeni negativni zaključak da robustan prenos nije potvrđen u ovom skupu.

Široki korpus ne može povećati nazivnik Top-1 jer svaki njegov prije/poslije par sadrži ishod samo jedne intervencije. Nedostajući ishodi ostalih intervencija ne smiju se tretirati kao nule ili kao porazi.
