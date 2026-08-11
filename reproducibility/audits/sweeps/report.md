# Audit konstrukcije korpusa i sweep izvrsavanja

## Zakljucak

Offline validator je zavrsio sa statusom `PASS_WITH_LIMITATIONS`: 75 provjera, 74 prolaza, bez tvrdih gresaka i sa jednim upozorenjem o prenosivosti apsolutnih putanja. Broj izvrsenja, prosirenje ponavljanja, zakljucani redoslijedi, vremenski ugovori i objavljeni sazetci kanonizacije medjusobno su saglasni.

Paket je dovoljan da se provjere dizajn i integritet svih trazenih programa. Nije dovoljan za jedan potpuno samostalan live rerun svih mjerenja. Glavni razlozi su nedostajuci sirovi indeksi za neke kasnije panele, izvorne apsolutne putanje, nepostojanje dumpa baze i cinjenica da svako historijsko izvrsenje nema u paketu ugradjen tacan source snapshot svog radnog stabla.

Validator se pokrece komandom:

```bash
python3 reproducibility/audits/sweeps/audit.py
```

Masinski nalaz je u `findings.json`.

## Kako se korpus pretvara u izvrsenja

Osnovna jedinica manifesta je uslov, odnosno jedna kombinacija SQL instance, skupa podataka, runtime konfiguracije, topologije i uloge intervencije. Renderer zatim prosiruje svaki uslov na trazeni broj ponavljanja. Svako ponavljanje dobija zaseban `repetition_index`, `repeat_id` i `execution_slot_id`. Tek nakon tog prosirenja redovi se uredjuju i dobijaju `run_order`.

Ovaj ugovor je neposredno vidljiv u:

- `sources/master-regimes/src/master_regimes/corpus_adapter.py:501-555` za prosirenje uslova i formiranje fizickog slota;
- istoj datoteci, redovi 422-444, za deterministicki SHA-256 poredak;
- redovi 447-498 za eksplicitni raspored koji mora jednoznacno pokriti svaki prosireni red;
- redovi 557-588 za izbor politike i dodjelu `run_order`.

Runner cita vec uredjen `instance_manifest.csv` i izvrsava redove sekvencijalno. Ne pokrece paralelne upite i podrazumijevano ne radi eksplicitan cache reset ni poseban warm-up. To je zapisano u `sources/master-regimes-infra/common-scripts/run_query_collection_sweep.py:617-648`.

## SQL datoteka nije isto sto i fizicko izvrsenje

Jedna renderovana SQL datoteka opisuje tekst jednog uslova. Ponavljanja ne moraju kopirati isti tekst u pet datoteka. Pet redova manifesta mogu pokazivati na istu SQL datoteku, ali imaju razlicite fizicke slotove, vremena, planove i telemetriju.

To objasnjava sljedece odnose:

| Program | SQL datoteke | Uslovi | Fizicka izvrsenja | Razlog |
| --- | --: | --: | --: | --- |
| zajednički clean/F19-F21 | 1.964 | 1.964 | 1.964 | nema ponavljanja uslova |
| pressure | 799 | 869 | 2.607 | tri ponavljanja; placement stanja mogu dijeliti SQL |
| DBA panel | 60 | 60 | 180 | broj pojava SQL-a raste od 1 do 5 |
| N2/N3 | 180 | 180 | 180 | faze su zasebno renderovane, bez ponavljanja |
| confirmatory | 60 | 60 | 300 | pet ponavljanja istog uslova |
| feedback loop | 9 kanonskih stanja | putanje/replay | 85 + 25 | ista stanja se ponavljaju i replayaju |

Konfiguracijske i mrezne intervencije dodatno mogu koristiti potpuno isti SQL. Razlika tada nastaje u runtime profilu, GUC postavci ili mreznom stanju, a ne u tekstu upita. Zbog toga broj SQL datoteka ne smije biti tumacen kao broj izmjerenih izvrsenja.

## Provjera pojedinacnih programa

### Zajednički clean/F19-F21 korpus

- Osam renderovanih grupa daju tacno 1.964 reda.
- Svaki red ima zasebnu SQL datoteku i `repetition_index=0`.
- Redoslijed je `deterministic_shuffle` sa sjemenom `20260626`.
- Logicki indeks iz `artifacts/logical-indexes/clean-run-v1.tar.gz` ima 1.964 `query_runs` reda, 1.964 razrijesena upita i nula zahtjeva za ponovni run.
- Podjela je 955 izvrsenja nad `pilot-balanced-v1` i 1.009 nad `pilot-skew-heavy-v1`.

Ovaj blok ima najslabiji vremenski ugovor. Od 1.964 SQL instance, 1.718 koristi `now()`, 240 koristi `current_date`, a sest nema zidni sat. Svaki od osam sweepova je neposredno prije mjerenja ponovo generisao svoj dataset, a najduzi sweep trajao je oko 3,686 sati. Post-hoc NMI provjera nije nasla materijalnu vezu izmedju kvartila redoslijeda i tvrde FCM grupe (`0,00110`). To podrzava internu opisnu analizu arhiviranih rezultata, ali danasnje pokretanje istog SQL-a ne bi bilo isti vremenski eksperiment.

Izvor: `releases/temporal-validity-audit-v1/temporal_validity_audit.json`.

### Siroki pressure program

- 869 uslova je prosireno na tacno tri ponavljanja, ukupno 2.607 slotova.
- Postoji 418 kontrolisanih comparison grupa i 13 profila dataseta.
- Svih 2.607 `param_json` zapisa nosi `as_of_unix=1782864000`.
- Standardni backend ima 2.187 izvrsenja. Placement-aware worker backend ima 420 izvrsenja u 14 uredjenih putanja po 30 slotova.
- Raspodjela domena je: GAC 594, regionalna finalizacija 477, udaljena putanja 522, repartition join 594 i worker skew 420.

Naziv "418 parova" zahtijeva jednu nijansu. Svih 418 grupa sadrzi stressed i mitigated kontrast. Njih 385 ima dva uslova i sest izvrsenja, dok 33 grupe cuvaju i intermediate uslov, pa imaju tri uslova i devet izvrsenja. Broj 418 je zato broj planiranih kontrastnih grupa, a ne tvrdnja da svaka grupa sadrzi iskljucivo dva stanja.

Program je izveo 869 result-signature provjera, samo na prvom ponavljanju svakog uslova. Time je izbjegnuto 1.738 redundantnih ponovnih upita za isti rezultat, ali su sva tri instrumentovana izvrsenja zadrzana za performansne dokaze.

Kanonizacijski sazetak prijavljuje 3.027 uspjesnih kandidata pokusaja. Izabrano je 2.607 primarnih slotova, 420 kandidata je iskljuceno, a nema nedostajuceg, neocekivanog ili dvostruko izabranog primarnog slota. Pravilo je `latest_successful_program_attempt`. Njegova implementacija grupise po batchu, segmentu i slotu, a pobjednika bira po vremenu zavrsetka, broju pokusaja i redu checkpointa: `sources/master-regimes/analysis/scripts/agent/86_consolidate_pressure_raw_program.py:471-512`.

Vremenski audit razdvaja 397 sadrzajnih parova sa zamrznutim ili vremenski nezavisnim ugovorom od 21 `current_date` prazne negativne kontrole. Ove 21 grupe podrzavaju provjeru collectora i jednakosti praznog rezultata, ali ne dokaz efekta intervencije.

### Zavrsni DBA panel

- 15 SQL oblika imaju po cetiri uslova: baseline i tri intervencije.
- Dobijeno je 60 uslova, 60 SQL datoteka i 180 fizickih izvrsenja.
- Broj pojava SQL-a slijedi obrazac `1,2,3,4,5`, ponovljen u tri grupe po pet upita. Zbir daje 45 tacaka odluke.
- Svaka od cetiri dataset grupe ima potpun, neprekinut `run_order`.
- Redoslijed je `deterministic_interleaved_shuffle(seed=20260805)`.

Ovdje "tri pojavljivanja prosjecno" ne znaci tri kopije svake SQL datoteke. Uslov ima jednu datoteku, a svako pojavljivanje novi `execution_slot_id`.

### Kontrolisani N2/N3 panel

Manifest i renderovani blokovi se podudaraju:

| Blok                | Izvrsenja |
| ------------------- | --------: |
| N2 kontrola         |        60 |
| N3 faza A, baseline |        15 |
| N3 faza A, akcije   |        45 |
| N3 faza B, baseline |        15 |
| N3 faza B, akcije   |        45 |
| Ukupno              |       180 |

Svaki uslov ima jedno izvrsenje. Izraz "60 po krugu" ovdje znaci 15 scenarija puta cetiri uslova, a ne ponavljanje jednog uslova. Blokovi imaju zasebna zakljucana sjemena `202608061` do `202608065`. Provenance biljezi pravilo `latest_successful_logical_slot`, cuvanje neuspjelih pokusaja i nula automatskih retryja.

### Potvrdni panel od 300 izvrsenja

- 15 novih SQL oblika puta cetiri uslova daje 60 uslova.
- Svaki uslov ima pet ponavljanja, ukupno 300 izvrsenja.
- Postoji 60 SQL datoteka, ne 300.
- Eksplicitni Williamsov raspored je potpuno pokriven i jednak stvarnom `run_order` zapisu.
- Svaka intervencija se pojavljuje 18 ili 19 puta na svakoj od cetiri pozicije. Potpuna jednakost nije moguca jer 75 pojava tretmana nije djeljivo sa cetiri.
- Collection audit navodi 300 zavrsenih izvrsenja, 3.000 node artefakata, 900 edge zapisa, 900 regionalnih fragmenata i 57.600 worker/task fragmenata.

Zakljucani ugovor je u `sources/master-regimes/configs/validation/confirmatory_action_replication_v1.yml:1-61`. On eksplicitno navodi pet ponavljanja, 300 izvrsenja, Williamsov redoslijed, timeout i nula automatskih retryja.

### Feedback loop i zamrznuti replay

Glavni `execution_manifest.csv` sadrzi 85 fizickih redova:

- jedan smoke;
- 15 pocetnih;
- pet correctness-only;
- 15 adaptivnih;
- devet rollback;
- 40 replay izvrsenja.

Od 40 replay redova, 20 je kanonsko, a 20 je zadrzano sa statusom `superseded_invalid_configuration`. Completion manifest zato pravilno razlikuje 60 kanonskih instrumentovanih, pet correctness-only i 20 superseded izvrsenja.

Aggregate-exact dodatak ima 25 izvrsenja: cetiri stanja po pet pojavljivanja u balansiranom rasporedu i zavrsni rollback sa pet ponavljanja. Glavni decision log ima pet odluka i pet ishoda, a aggregate log tri odluke i tri ishoda. U svim slucajevima timestamp odluke prethodi timestampu ishoda.

Vremenski ugovor za measured SQL zamrzava `base_time_unix=1782864000` i zabranjuje zidni sat. To je eksplicitno u `sources/master-regimes/experiments/feedback-loop-v1/query_trajectory_manifest.yaml:7-19`.

## Segmentacija, nastavak i timeout

Sweep runner je sekvencijalan. Za svaki red poziva jedan query collector i prosljedjuje hard timeout. Timeout dobija eksplicitan status i runner prelazi na naredni planirani slot. Checkpoint se ne upisuje samo zato sto proces postoji. Slot je resumable tek nakon sto postoji collection direktorij, execution manifest ili status i potvrda `execution_status=completed`. Tek poslije atomskog upisa parcijalnog sweep manifesta upisuje se append-only checkpoint i radi `fsync`.

Dokaz je u:

- `sources/master-regimes-infra/common-scripts/run_query_collection_sweep.py:562-580`;
- ista datoteka, redovi 698-715, za skip samo potvrdenih slotova;
- redovi 1094-1165 za redoslijed manifest, checkpoint i `fsync`.

Pressure orchestration dodatno dijeli program na dataset/runtime segmente. Zavrseni segment se priznaje samo ako checkpoint pokriva sve ocekivane slotove. Pri nastavku se povecava broj pokusaja segmenta, a ponovno se izvrsavaju samo nedostajuci slotovi. Izvor: `sources/master-regimes/analysis/scripts/agent/78_run_pressure_raw_batch.py:685-780,846-875,1148-1159`.

To znaci da retry ne prepisuje historiju. Stari i novi pokusaji ostaju dostupni, a konsolidacija bira jedan kanonski uspjesan pokusaj. Za N2/N3 i confirmatory ugovore automatski broj retryja je nula: timeout ili kvar ostaju eksplicitni, a operator moze pokrenuti novi, zasebno evidentiran pokusaj.

## Sta paket moze sam dokazati

Paket omogucava nezavisnu offline provjeru:

1. broja SQL uslova i fizickih slotova;
2. SHA-256 vrijednosti svih 3.819 katalogizovanih SQL datoteka;
3. prosirenja ponavljanja i jedinstvenosti slotova;
4. deterministickih sjemena i potpunosti `run_order` zapisa;
5. Williamsovog rasporeda i njegove pozicijske ravnoteze;
6. temporalnih modova i zamrznutih `as_of` parametara;
7. objavljenih completion, leakage, result-equivalence i consolidation gateova;
8. redoslijeda decision log odluka prije njihovih ishoda;
9. zajedničkog clean/F19-F21 sirovog i logičkog index arhiva.

## Sta se ne moze ponovo izvesti iz paketa bez dodatnog rada

1. **Direktan live rerun iz renderovanih manifesta.** U 8.391 od 9.375 pregledanih manifest referenci SQL putanja je apsolutna i pokazuje na izvorni `<home>/...` layout. SQL je prisutan preko relativnog kataloga, ali runner ne cita taj katalog. Potrebno je regenerisati manifeste ili prepisati putanje.

2. **Bit-identican dataset poslije novog load-a.** Paket sadrzi profile, sjeme, generator i `base_time`, ali nema dump niti puni row-level checksum ucitane baze. Ponovljivost je konstrukcijska, ne nezavisno potvrdena novim reloadom.

3. **Nezavisna kanonizacija svih kasnijih pokusaja.** Clean ima sirove i logicke arhive. Pressure paket sadrzi consolidation manifest, ali ne i svih 3.027 candidate redova i potpuni primarni `_index`. DBA, N2/N3, confirmatory i feedback uglavnom objavljuju konsolidovane izvode, ne sve collection direktorije.

4. **Potvrda confirmatory raw indeksa.** `input_manifest.json` cuva hash i velicinu velikih `query_runs`, `execution_features` i worker/task tabela, ali same datoteke nisu u paketu.

5. **Tacan historijski executable source za svaki run.** Paket ima kurirane source snapshotove, ali pojedini runovi navode starije commitove, a feedback provenance biljezi dirty `master-regimes` i thesis radno stablo. To se ne smije retroaktivno izjednaciti sa danasnjim source snapshotom.

6. **F19/F21 korpus kao isti vremenski eksperiment danas.** Pomični `now()` i `current_date` zahtijevali bi rekonstrukciju vremenskog oslonca svakog sweepa.

7. **Aggregate-exact dataset iz samog releasea.** Zabiljezeni su `base_time` i audit brojeva, ali nije sacuvan tacan naziv zakljucanog dataset profila.

8. **Live infrastruktura.** Credentials, Terraform state, provider account, generisani Ansible inventory i VPS snapshot nisu dio paketa. Ovaj audit ne tvrdi da se infrastruktura trenutno moze podici bez tih ulaza.

9. **Identicno trajanje i plan.** Isti SQL i dataset nisu dovoljni za identican plan ili runtime bez istih verzija, statistika, cache stanja, VPS rasporeda i mreznog profila.

## Ocjena reproducibilnosti

Eksperimentalni dizajn je dobro rekonstruisan i interno konzistentan. Zajednički clean/F19-F21 korpus najpotpuniji je po dostupnosti sirovih indeksa, ali je najslabiji po temporalnoj ponovljivosti. Kasniji DBA, N2/N3, potvrdni i feedback paneli imaju bolji zamrznuti vremenski i redoslijedni ugovor, ali objavljuju manje sirovih podataka prikupljanja.

Najpreciznija zavrsna tvrdnja je:

> Paket omogucava nezavisnu provjeru konstrukcije korpusa, brojeva, SQL sadrzaja, rasporeda, temporalnih ugovora i objavljenih validacijskih gateova. Za puni live rerun potrebni su adapter putanja, ponovna infrastruktura, historijski izvori i dio sirovih indeksa koji trenutno nisu ukljuceni.
