# Audit ponovljivosti skupova podataka i stvarnog eksperimentalnog obuhvata

**Status:** `PASS_WITH_WARNINGS`. Audit je potpuno offline; SQL i infrastruktura nisu pokretani.

## Sažetak

Glavni empirijski blokovi ne koriste jedan homogeni skup podataka. Zajednički karakterizacijski korpus modela F19 i F21 koristi dvije pilot varijante, sirovi intervencijski program koristi 13 profila, završni DBA panel koristi četiri balansirana profila, a kontrolisani N2/N3 i potvrdni panel koriste posebne topology-isolation parove. To je metodološki prihvatljivo samo ako se zaključci ograniče na ulogu svakog bloka.

Postoji stvarno izvršen slučaj u kojem je **EU logički region imao hot-tenant raspodjelu, a US region balansiranu raspodjelu**. To je `pilot-region-local-skew-asymmetric-medium-v1`. Profil ima jednak broj tenant-a u oba regiona, ali EU nosi 5% hot tenant-a sa 65% događaja, dok je US uniforman. Ovaj slučaj je prisutan u companion korpusu i u wide worker-data-skew osi. Ipak, profil ne deklarira generički `supports_shard_skew`; termin _worker skew_ ovdje opisuje opaženu posljedicu hot tenant-a i njihovog shard/task rasporeda, a ne različit broj shardova po regionu [sources/master-regimes/datasets/profiles/pilot-region-local-skew-asymmetric-medium.yml:13-28, 38-43, 77-92; artifacts/rendered-corpora/pressure-raw-v1/execution_matrix.csv: redovi sa `dataset_profile_id=pilot-region-local-skew-asymmetric-medium-v1` i `pressure_axis=worker_data_skew`].

## Skupovi po dokaznom bloku

| Dokazni blok | Stvarno korišteni skupovi | Jedinice u paketu | Ugovor ponovnog učitavanja |
| --- | --- | --: | --- |
| Zajednički F19/F21 karakterizacijski korpus | `pilot-balanced-v1` (955), `pilot-skew-heavy-v1` (1009) | 1964 kataloških redova | Slabiji: arhivirani load manifesti imaju `base_time=0`; tačan savremeni reload nije garantovan. |
| Široki intervencijski korpus | `pilot-balanced-v1` (187), `pilot-balanced-wide-global-dim-v1` (32), `pilot-region-local-skew-asymmetric-medium-v1` (10), `pilot-skew-heavy-v1` (10), `raw-large-balanced-v1` (223), `raw-large-balanced-wide-global-dim-v1` (32), `raw-large-skew-heavy-v1` (10), `raw-large-skew-moderate-v1` (10), `raw-medium-skew-moderate-v1` (10), `raw-small-balanced-v1` (223), `raw-small-balanced-wide-global-dim-v1` (32), `raw-small-skew-heavy-v1` (10), `raw-small-skew-moderate-v1` (10) | 799 kataloških redova | Jak za 397 sadržajnih parova; 21 `current_date` para su samo prazne no-work kontrole. |
| Završni DBA panel | `n3-large-balanced-wide-global-dim-v1` (12), `n3-medium-balanced-wide-global-dim-v1` (16), `raw-large-balanced-v1` (16), `raw-small-balanced-v1` (16) | 60 kataloških redova | Fiksni profil, sjeme, `base_time`, shard count i SQL cutoff. |
| Kontrolisani N2/N3 panel | `topology-isolation-large-n2-v1` (16), `topology-isolation-large-n3-v1` (32), `topology-isolation-medium-n2-v1` (16), `topology-isolation-medium-n3-v1` (32), `topology-isolation-small-n2-v1` (16), `topology-isolation-small-n3-v1` (32), `topology-isolation-xlarge-n2-v1` (12), `topology-isolation-xlarge-n3-v1` (24) | 180 kataloških redova | Fiksni upareni N2/N3 profili; isti logički podaci se razdvajaju na tri fizička regiona. |
| Potvrdni action panel | `topology-isolation-large-n3-v1` (60) | 60 kataloških redova | Najjači ugovor: jedan fiksni N3 profil i pet ponavljanja svakog uslova. |
| Longitudinalni feedback loop | `locked_current_dataset_snapshot` (9) | 9 kataloških redova | Interni before/after audit je jak, ali izvorno ime profila, sjeme i shard count nisu zabilježeni. |
| Potvrdna skew provjera | `pilot-balanced-v1` (12), `pilot-region-imbalanced-v1` (12), `pilot-skew-heavy-v1` (24) | 48 kataloških redova | Fiksni pilot profili; razlikuje placement kontrast od regionalnog volumena. |

Broj kataloških redova nije uvijek broj fizičkih izvršenja. Na primjer, potvrdni panel ima 60 SQL-uslov instanci, ali pet ponavljanja, odnosno 300 izvršenja; završni DBA panel ima 60 SQL-uslov instanci i 180 izvršenja. Autoritativni zbirni brojevi su u [reproducibility/evidence-blocks.json:1-53].

## Parametri i raspodjele

- Većina novijih sintetičkih profila koristi `base_time_unix=1782864000` (`2026-07-01 00:00:00 UTC`) i `lookback_days=30`. Sjeme 42 koristi pilot porodica, 73 raw i large topology-isolation porodica, 142 medium N3, a 242 large/xlarge N3 porodica [reproducibility/dataset-catalog.csv:3-30].
- Shard count varira sa veličinom: 16, 32 ili 64. Prazna polja za topology-isolation profile u katalogu su greška ekstrakcije iz inline YAML zapisa; sami profili sadrže vrijednosti, npr. 64 za large N3 [reproducibility/dataset-catalog.csv:23-30; sources/master-regimes/datasets/profiles/topology-isolation-large-n3.yml:21].
- `pilot-region-imbalanced-v1` ima EU:US tenant raspon 1800:200 uz balansiranu raspodjelu unutar tenant-a. To je region-level data imbalance, ne hot-tenant ili worker/shard skew [sources/master-regimes/datasets/profiles/pilot-region-imbalanced.yml:13-22, 32-37, 53-60].
- `pilot-skew-heavy-v1` raspoređuje hot tenant-e u cijelom dvoregionalnom profilu. `pilot-region-local-skew-asymmetric-medium-v1` je posebna varijanta u kojoj je EU skewed, a US balanced [sources/master-regimes/datasets/profiles/pilot-region-local-skew-asymmetric-medium.yml:13-28].
- N3 topology-isolation profili nisu 1:1:1 volumenski balansirani po fizičkom regionu: large N3 je 2000:1000:1000 tenant-a. To čuva isti logički N2 skup tako što se raniji US raspon dijeli između US i APAC, a ne uvodi hot-tenant skew [sources/master-regimes/datasets/profiles/topology-isolation-large-n2.yml:13-20; sources/master-regimes/datasets/profiles/topology-isolation-large-n3.yml:13-21, 29-34].

## Stvarni obuhvat worker i regionalne neravnoteže

Wide matrica sadrži 420 izvršenja na osi `worker_data_skew`, od čega 60 koristi EU-only hot-tenant profil. To odgovara 140 konfiguracija, 70 kontrafaktualnih parova i sedam dataset profila navedenih u manifest auditu [artifacts/rendered-corpora/pressure-raw-v1/manifest_coverage_audit.json:143-171].

Potvrdni skew panel ne treba opisivati kao još jedan EU-only slučaj. Njegove B/C faze koriste globalni `pilot-skew-heavy` i mijenjaju raspored hot shardova u oba regiona, dok faza D koristi 9:1 regionalni volumen. Time se odvojeno provjeravaju placement-sensitive worker skew i region-level imbalance [reproducibility/query-catalog.csv: redovi sa `evidence_block=controlled_skew_validation`].

Završni DBA, N2/N3 topology-memory i potvrdni action panel ne koriste hot-tenant/skew profile. Zato njihove action-selection tvrdnje ne obuhvataju worker-skew intervencije [reproducibility/query-catalog.csv: redovi za `final_dba_panel`, `controlled_topology_memory_panel` i `confirmatory_action_panel`].

## Ponovljivost i granice valjanosti

1. **Zajednički korpus modela F19 i F21 nije tačno temporalno ponovljiv današnjim ponovnim pokretanjem.** Arhivirani load manifesti imaju `DATAGEN_BASE_TIME_UNIX=0`; generator tada koristi zidni sat. Ipak, arhivirane analize ostaju deskriptivno upotrebljive jer su dataset i SQL u svakom sweepu dijelili isti vremenski oslonac, lag je bio ograničen i NMI sa vremenskim kvartilom je približno nula za oba modela [releases/temporal-validity-audit-v1/temporal_validity_audit.json; sources/citus-datagen/tools/cpp/citus_datagen.cpp:313-317, 428-459].
2. **Wide rezultat nije jednako jak za svih 418 parova.** Svih 418 je rezultatski ekvivalentno, ali 21 `current_date` par je prazna no-work negativna kontrola; 397 parova podržava sadržajna poređenja intervencija [releases/temporal-validity-audit-v1/temporal_validity_audit.json:77-96].
3. **Feedback-loop snapshot nije moguće tačno reloadati iz samog paketa.** `base_time` i lookback su sačuvani, ali izvorno ime profila, sjeme i shard count nisu [reproducibility/dataset-catalog.csv:2; reproducibility/README.md:63-70]. To ne poništava before/after nalaz na istom snapshotu, ali ograničava bit-for-bit reprodukciju dataseta.
4. **Nema row-level checksum cijelog sintetičkog dataseta.** Paket čuva profile, hash profila, SQL hashove i generator source snapshot, ali ne i dump ili checksum svakog reda. Ponovno generisanje je determinističko samo kada su originalni commit generatora, profil, sjeme, `base_time` i način učitavanja poznati [reproducibility/evidence-blocks.json:48-53].
5. **Pripremljeno nije isto što i izvršeno.** Combined holdout, N3 holdout i sentinel batch širokog programa nisu dio 2.607 izvršenja; manifest ih označava kao `prepared_not_executed` ili blokirane [artifacts/rendered-corpora/pressure-raw-v1/manifest_coverage_audit.json:257-296].

## Integritet paketa za provjeru i ponovno izvođenje

Svih 29 kataloških profila ima dostupan sadržaj i odgovarajući SHA-256. Validator je pronašao 90 relativnih referenci koje više ne rade iz kurirane lokacije renderovanog korpusa; svih 90 može se razriješiti po istom nazivu u `sources/master-regimes/datasets/profiles/`. To je problem prenosivosti putanje, ne nestao dataset profil.

Vanjski STATS/CEB dump nije ugrađen u paket, ali je izvor zaključan Zenodo identifikatorom i checksumovima [sources/master-regimes/external/stats-ceb/source-lock.yml:1-33].

## Pokretanje

```bash
python3 reproducibility/audits/datasets/audit.py
```

Skripta ponovo generiše `findings.json` i ovaj izvještaj. Izlazni status `PASS_WITH_WARNINGS` znači da su autoritativni katalozi i brojevi konzistentni, ali da postoje dokumentovane granice tačnog ponovnog učitavanja i prenosivosti paketa.
