# Obim paketa za provjeru i ponovno izvođenje

## Namjena

Paket podržava četiri različita nivoa provjere:

1. **Integritet** provjerava SHA-256 svih objavljenih fajlova.
2. **Offline ponovno računanje** ponavlja obradu objavljenih CSV/JSON artefakata, završnog `F19`, historijskog `F21-dev`, prostora `P64->6`, representation ablacije i longitudinalne analize bez baze.
3. **Dataset regeneracija** koristi uključeni DDL, generator, profil, sjeme i zamrznuti vremenski oslonac.
4. **Ponovno izvođenje eksperimenta** ponovo podiže PostgreSQL/Citus topologiju, renderuje SQL i prikuplja planove. Zahtijeva VPS resurse i troši novac.

Offline rezultat je provjera objavljenih brojeva. Novi infrastrukturni run ponavlja eksperimentalni postupak, ali drugi CPU, planer, cache ili mrežni šum mogu promijeniti apsolutno trajanje.

## Uključeni dokazni tokovi

| Tok | Uloga | Glavni ulazi |
| --- | --- | --- |
| Karakterizacijski korpus | `F19` i odgovori na RQ1-RQ4 | `clean-run-v1` i prateći korpusi |
| Široki intervencijski korpus | collector, rezultatska jednakost i 418 prije/poslije parova | 799 autoritativnih SQL fajlova, 869 uslova i 2.607 izvršenja |
| Završni DBA i topology paneli | vremenski korektna lokalna memorija i kontrolisani N2/N3 pomak | 60 + 180 SQL instanci |
| Potvrdni panel | novi SQL oblici i pet balansiranih ponavljanja | 60 uslova i 300 izvršenja |
| Longitudinalne putanje | praktična analiza deklarisane DBA intervencije | devet kanonskih SQL stanja, odluke, rollback i replay |

Tačne putanje nalaze se u `reproducibility/evidence-blocks.json`, a svaki SQL u `reproducibility/query-catalog.csv`.

## Uključeni izvori

- collector, indexer i infrastrukturni runner;
- generator i loader sintetičkih podataka;
- dataset profili, seedovi, temporalni oslonci i regionalni rasponi;
- SQL template-i i stvarno renderovani SQL glavnih eksperimenata;
- raw planovi i logical-run indeksi potrebni za objavljene tvrdnje;
- feature matrice i odvojeni zamrznuti ugovori `F19` i `P64->6`, uz historijski `F21-dev`;
- puni feedback-loop decision, execution, result i rollback audit;
- representation ablacije, potvrdni rezultati i temporalni audit;
- kurirane studije `CASE-*` i `Q08-NEIGHBORS`.

## Namjerno izostavljeno

- database dumpovi i SQL rezultatni redovi;
- Terraform state, privatni ključevi, lozinke i cloud credential-i;
- višekratne kopije gigabajtnih worker fragmenata kada isti dokaz postoji u logical indeksu i sažetom releaseu;
- smoke/probe runovi koji nisu dio tvrdnji;
- napušteni modeli, notebooki, interni promptovi i razvojne biljeske;
- rukopis, LaTeX i PDF renderi.

Odsustvo database dumpa ne znači da dataset ugovor nedostaje. Sintetički skup se rekonstruise iz verzionisanog generatora i profila. Nije, međutim, sačuvan puni row-level checksum svake tabele, pa paket ne tvrdi nezavisnu bit-po-bit potvrdu novog učitavanja.

## Završna arhitektura rezultata

Primarni praktični izlaz nije Ridge ili kNN preporuka. To je provjeren zapis:

```text
povezano izvršenje prije
-> deklarisana intervencija
-> povezano izvršenje poslije
-> provjera rezultata
-> promjena R6, sirovih signala i trajanja
-> trajni lokalni zapis
```

`F19` opisuje kompozitne fizičke obrasce i odgovara na fiksna istraživačka pitanja. `F21-dev` je ranija razvojna ablacija. `P64->6`, kNN, FCM-PCA/K-means kompresija i raniji Ridge model ostaju sekundarne evaluacije. Potvrdni panel nije podržao univerzalni cross-query prijenos, pa paket nijedan od tih postupaka ne predstavlja kao opći optimizer.

## Provjera

```bash
make reproducibility-catalog
make verify
```

Prva komanda gradi navigacijske kataloge. Druga provjerava kataloge, source commitove, release ugovore, logical arhive i globalni SHA-256 manifest.
