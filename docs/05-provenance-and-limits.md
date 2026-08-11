# Porijeklo dokaza i granice reprodukcije

## Source snapshoti

Tačni commitovi su u `config/release-spec.json` i `reproducibility/source-provenance.csv`. Kurirani snapshoti uključuju izvršni kod, testove, konfiguracije i analitičke skripte potrebne za objavljene rezultate. Razvojni notebooki, promptovi, credential-i i generisani radni direktoriji nisu dio snapshot-a.

## Vrste porijekla podatka

- `recorded_at_run_time`: direktno zapisano tokom izvršenja;
- `reconstructed_from_versioned_config`: izvedeno iz verzionisanog profila ili ugovora;
- `not_recorded`: podatak nije dostupan i ne predstavlja mjerenje.

Oznaka logičkog regiona (`EU`, `US`, `APAC`) nije dokaz fizičke provider lokacije. Završna topologija bila je logički geo-distribuirana, ali su VPS instance bile fizički kolocirane u Amsterdamu. WAN uslovi su kontrolisano emulirani pomoću `tc/netem`.

## Dataset porijeklo

Za novije glavne eksperimente dataset identitet vezuje:

```text
profil + commit generatora + seed + base_time_unix
+ lookback + regionalni rasponi + shard ugovor
```

Zamrznuti oslonac je `1782864000` (`2026-07-01T00:00:00Z`). SQL fallback na `now()` može tekstualno ostati u pojedinim template-ima, ali je u izvedenim glavnim SQL instancama prva grana `coalesce` vezana za nenulti zamrznuti `as_of_unix`. Temporalni audit čuva ovu razliku.

Nije sačuvan puni row-level checksum svake tabele. Regeneracija je deterministička konstrukcijom, ali novi reload nije nezavisno potvrđen bit-po-bit. Zajednički `clean-run-v1` korpus modela `F19` i `F21-dev` ima slabiji temporalni ugovor i zato podržava arhivirani deskriptivni rezultat, ne tvrdnju o identičnom budućem rerunu.

Feedback loop koristi zabilježeni `locked_current_dataset_snapshot`. Njegov SQL, broj redova, result hash, planovi i izvršni ishodi su sačuvani, ali naziv izvornog generator profila nije. Taj rezultat ostaje valjan kao kontrolisana prije/poslije analiza na jednom snapshotu; potpuno novo učitavanje istog skupa nije garantovano.

## Šta se provjerava tačno

- sadržaj objavljenih fajlova preko SHA-256;
- svaki katalogizovani SQL i njegov dataset profil;
- broj redova logical indeksa;
- zamrznuti `F19`, historijski `F21-dev`, representation ablacije i leakage provjere;
- 418 kontrolisanih prije/poslije parova;
- DBA, N2/N3 i potvrdni paneli;
- feedback-loop decision log, result audit, rollback i replay;
- figure i numerički izvori na kojima se zasnivaju.

Kod širokog programa svih 418 grupa ima stressed/mitigated kontrast. Njih 397 sadrži podatke pogodne za poređenje učinka intervencije, dok je 21 `current_date` grupa dala prazne no-work rezultate. Te kontrole provjeravaju collector i jednakost praznog rezultata, ali ne podržavaju tvrdnju o učinku.

## Šta se reprodukuje proceduralno

- dodjela VPS hardvera i CPU steal;
- apsolutna vremena izvršavanja;
- provider mreža i host-level OS sum;
- plan nakon promjene PostgreSQL/Citus verzije ili statistika;
- svježi dataset reload bez row-level checksum potvrde.

Planski i task-level dokazi imaju neposredniju vezu sa SQL izvršenjem od OS uzoraka. OS CPU i mreža tumače se kao ambijentalni kontekst, ne kao izolovana query-level potrošnja.

## Granice tvrdnji

- `R6` opisuje relativnu promjenu šest domena; nije dekompozicija uzroka ni procentualni doprinos trajanju;
- `F19` prototipi zavise od karakterizacijskog korpusa, dok je `F21-dev` samo ranija razvojna ablacija;
- fuzzy članstvo nije vjerovatnoća uzroka ni očekivano ubrzanje;
- fizička blizina u `P64->6` ne garantuje isti odziv na intervenciju;
- potvrdni panel nije podržao univerzalni cross-query prenos;
- direktna historija zahtijeva eksplicitno definisan SQL ili `logical_question_id` ugovor;
- Ridge, kNN, K-means i FCM memorija ostaju sekundarne evaluacije, ne autonomni optimizer;
- rezultati pokazuju kontrolisano emulirane WAN uslove, ne stvarne cloud interregionalne putanje;
- database rezultatni redovi nisu objavljeni, ali su sačuvani multiset i ordered hash ugovori potrebni za provjeru jednakosti.

Potpuni offline nalaz, uključujući asimetrični regionalni skew, sweep slotove i collector roditeljske veze, nalazi se u `reproducibility/audits/REPRODUCIBILITY_AUDIT.md`.

## Privatnost i prenosivost javnog paketa

Objavljeni tekstualni artefakti i kompresovane logical/raw arhive sanitizovani su prije izgradnje release manifesta. Apsolutni home prefiksi zamijenjeni su relativnim putanjama, runtime javne i privatne IP adrese neutralnim oznakama, a historijski demo domen dokumentacijskim domenom. Logički identiteti čvorova, topologija, SQL, planovi, vremena i fizičke metrike nisu uklonjeni.

Komanda `make public-check` provjerava trenutno stablo, dok `make public-audit-full` provjerava i sadržaj kompresovanih arhiva te bilježi stanje Git historije. Ranije objavljeni commit objekti mogu zadržati stare lokalne putanje. Njihovo uklanjanje zahtijeva zaseban rewrite historije i nije dio obične izgradnje release paketa.
