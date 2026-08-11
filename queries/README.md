# SQL upiti korišteni u radu

Ovdje se direktno nalaze čitljive kopije SQL instanci označenih sa `q01` do `q30`. Kopije su izvedene iz autoritativnih renderovanih corpusa i njihov SHA-256 je u [`thesis-query-index.csv`](thesis-query-index.csv).

- [`instances/final-panel-n2/`](instances/final-panel-n2/) sadrži N2 oblike `q01`-`q15`.
- [`instances/final-panel-n3/`](instances/final-panel-n3/) sadrži N3 oblike `q01`-`q15`.
- [`instances/confirmatory-panel-n3/`](instances/confirmatory-panel-n3/) sadrži nove `q16`-`q30`.
- [`template-index.csv`](template-index.csv) vodi do svih Jinja/SQL šablona u izvornom snapshotu.
- Puni katalog svih 3.819 renderovanih SQL fajlova ostaje u [`reproducibility/query-catalog.csv`](../reproducibility/query-catalog.csv).

Svaki upit ima `baseline` i `regional-topk` SQL. Akcije `work_mem` i udaljena mitigacija ne mijenjaju SQL tekst, pa koriste isti `baseline` fajl uz drugačiji runtime ugovor.

## Važna napomena o oznakama

Broj poput `q07` nije globalni identitet kroz sve corpuse. U završnom i N3 panelu oznaka je `q07_tenant_count`; stariji karakterizacijski corpus ima zaseban šablon `q07_global_user_segment_join`. Zato u citatima i indeksima uvijek treba koristiti puni naziv i corpus, a ne samo redni broj.

## q01-q30

| Upit | Analitička namjera |
| --- | --- |
| `q01_event_value_desc` | događaji sa najvećim vrijednostima |
| `q02_event_value_asc` | događaji sa najmanjim vrijednostima |
| `q03_event_recent` | najnoviji događaji nakon vremenske granice |
| `q04_event_oldest` | najstariji događaji nakon vremenske granice |
| `q05_event_deviation` | događaji sa najvećim odstupanjem vrijednosti |
| `q06_tenant_sum` | tenant grupe sa najvećim zbirom vrijednosti |
| `q07_tenant_count` | tenant grupe sa najvećim brojem događaja |
| `q08_tenant_avg` | tenant grupe sa najvećim prosjekom vrijednosti |
| `q09_tenant_max` | tenant grupe sa najvećom pojedinačnom vrijednošću |
| `q10_tenant_min` | tenant grupe rangirane po najmanjoj vrijednosti |
| `q11_tenant_high_count` | broj visokovrijednih događaja po tenantu |
| `q12_tenant_user_sum` | zbir vrijednosti po tenant-user grupi |
| `q13_tenant_user_count` | broj događaja po tenant-user grupi |
| `q14_tenant_day_sum` | dnevni zbir po tenantu |
| `q15_tenant_day_count` | dnevni broj događaja po tenantu |
| `q16_event_value_squared` | događaji rangirani kvadratom vrijednosti |
| `q17_event_log_value` | događaji rangirani logaritmom vrijednosti |
| `q18_event_recent_high_value` | noviji visokovrijedni događaji |
| `q19_event_old_low_value` | stariji niskovrijedni događaji |
| `q20_event_tenant_weighted` | događaji s tenant-ponderisanom vrijednošću |
| `q21_tenant_value_range` | raspon vrijednosti po tenantu |
| `q22_tenant_distinct_users` | broj različitih korisnika po tenantu |
| `q23_tenant_even_user_count` | broj događaja parnih korisnika po tenantu |
| `q24_tenant_midband_sum` | zbir srednjeg raspona vrijednosti po tenantu |
| `q25_tenant_day_avg` | dnevni prosjek po tenantu |
| `q26_tenant_hour_count` | satni broj događaja po tenantu |
| `q27_user_sum` | zbir vrijednosti po korisniku |
| `q28_user_count` | broj događaja po korisniku |
| `q29_user_value_range` | raspon vrijednosti po korisniku |
| `q30_user_day_sum` | dnevni zbir po korisniku |
