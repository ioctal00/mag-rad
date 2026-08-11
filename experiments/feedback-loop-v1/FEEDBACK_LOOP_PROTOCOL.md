# Protokol lokalne povratne sprege režima izvršavanja

## 1. Obuhvat

Ovaj paket operacionalizuje postojeća RQ2 i H1/H3, daje dodatni lokalni dokaz za RQ3 i zadržava RQ4 kao komparativno pitanje prototipske kompresije. Ne uvodi novo istraživačko pitanje i ne mijenja formulacije iz prijave teme. Autoritativna veza data je u [RQ_H_MAPPING.md](RQ_H_MAPPING.md).

Task 1 je isključivo offline priprema. Nijedna komanda iz kataloga intervencija ne izvršava se tokom validacije ili generisanja dry-run plana. Dataset, kolokacija, shard placement i indeksna struktura ostaju nepromijenjeni.

## 2. Jedinice posmatranja

Jedno prihvaćeno stanje `s_t` čine tri ponavljanja istog renderovanog SQL-a u istom deklarisanom kontekstu. Svako ponavljanje čuva sirove artefakte i sirove pokazatelje. Za pokazatelj `f` koristi se medijana dostupnih ponavljanja:

```text
m_t,f = median_r x_t,r,f
```

Nedostupan ili neprimjenjiv dokaz nije nula. Statusi su:

- `observed`: vrijednost je izmjerena;
- `not_applicable`: fizički sloj nije primjenjiv;
- `unavailable`: dokaz bi bio primjenjiv, ali nije prikupljen;
- `partial`: dostupna je samo dokumentovana podmjera;
- `insufficient_evidence`: nema dovoljno komponenti za domensku koordinatu.

## 3. Lokalni režim kao relativni profil

Šest domena je zamrznuto u [pressure_domain_manifest.yaml](pressure_domain_manifest.yaml):

1. udaljena FDW putanja;
2. regionalna redukcija;
3. GAC finalizacija;
4. neravnomjernost;
5. preljev na disk;
6. reparticionisanje i lokalnost.

Za referentno stanje `b` komponentna promjena računa se simetrično:

```text
d_t,f^(b) = direction_f * 2 (m_t,f - m_b,f)
             / (|m_t,f| + |m_b,f| + scale_t,b,f)
```

`scale_t,b,f` je lokalni MAD raspoloživih ponavljanja stanja `t` i `b`, uz mali numerički pod. Nije prag pritiska. Smjer se koristi samo kada manifest fizički opravdava da veća ili manja vrijednost predstavlja veću relativnu izraženost dokaza. Kontekstualne komponente ostaju u izvještaju, ali se ne agregiraju.

Domenska koordinata je ponderisana medijana dostupnih usmjerenih komponenti:

```text
p_t,d^(b) = weighted_median_f in domain(d) d_t,f^(b)
```

Lokalni režim za jednu referencu je:

```text
R_t^(b) = (p_t,1^(b), ..., p_t,6^(b))
```

Sistem čuva tri takva pogleda:

- `R_t^(origin)`: prema početnom stanju iste putanje;
- `R_t^(previous)`: prema neposredno prethodnom prihvaćenom stanju;
- `R_t^(history)`: prema isključivo ranijoj lokalnoj historiji istog `logical_question_id` i kompatibilnog konteksta.

Vrijednost veća od nule znači samo više relativnog dokaza u imenovanom domenu u odnosu na izabranu lokalnu referencu. Ne predstavlja univerzalno visok pritisak, dokazani osnovni uzrok ni poredivu jedinicu između domena.

## 4. Konfliktni signali i mali broj ponavljanja

Agregirana koordinata nikada nije jedini izlaz. Za svaki domen čuvaju se:

- sirove vrijednosti svakog ponavljanja;
- medijana trenutnog i referentnog stanja;
- relativna promjena svake komponente;
- status dostupnosti;
- broj pozitivnih i negativnih komponentnih promjena;
- oznaka `conflicting_component_signs`;
- lokalni MAD i interval ponovljivosti;
- porijeklo svakog artefakta.

Kod tri ponavljanja medijana je centralna vrijednost. Smjer ishoda određuje se tek nakon poređenja sa lokalnim šumom ponavljanja i sentinel historijom. Ako interval promjene prelazi nulu, ishod ostaje neodlučiv. Broj aktivnih domena, ako se prikaže, samo je broj domena sa raspoloživim lokalno razlučivim pomakom. Nije broj uzroka niti severity score.

## 5. Identitet izvršenja

Podržana su tri i samo tri slučaja:

1. `same_normalized_sql`: isti normalizovani SQL i kompatibilan kontekst;
2. `same_sql_declared_intervention`: isti normalizovani SQL, stabilan `action_id` i korisnički deklarisan `pair_id`;
3. `manual_logical_question_link`: različiti SQL oblici koje korisnik ručno veže istim `logical_question_id`, uz eksplicitan ugovor poređenja rezultata.

Automatska semantička sličnost SQL-a nije implementirana. `logical_question_id` je korisnička tvrdnja o analitičkoj namjeri, a ne modelski izvedena činjenica. Rezultatska provjera može tu tvrdnju prihvatiti ili odbiti za konkretan par.

## 6. Tranzicija i korisnička akcija

Prihvaćena tranzicija je:

```text
tau_t = (R_t, action_id, R_t+1, delta_outcome_t)
```

`action_id` može biti potpuno korisnički identitet, npr. `custom_change_17`. Sistem ne mora razumjeti njegovu semantiku da bi sačuvao prije/poslije dokaz. Semantičko razumijevanje i pravilo primjenjivosti postaju potrebni tek ako se akcija kasnije želi automatski predlagati.

`delta_outcome_t` najmanje sadrži logaritamski odnos medijana trajanja, interval lokalnog mjernog šuma, rezultatski status i višekriterijsku oznaku.

## 7. Adaptivni protokol

Za svaku od tri putanje postupak je:

1. Izvršiti tri početna ponavljanja i zaključati `R_0`.
2. Prije sljedećeg izvršenja pregledati samo artefakte stanja `t` i raniju historiju čiji je timestamp manji ili jednak `history_cutoff_utc`.
3. LLM zapisuje hipotezu, jednu akciju, ciljane domene i očekivani smjer u `decision_log.jsonl`.
4. Decision zapis dobija status `locked_pre_execution`. Ne sadrži outcome, after stanje ni buduće susjede.
5. Primijeniti samo jednu novu intervencijsku odluku i provjeriti primjenu.
6. Izvršiti tri ponavljanja stanja `t+1`, uz isti result contract.
7. Vratiti intervenciju i izvršiti rollback provjeru. Pozitivna akcija može zatim postati dio eksplicitno prihvaćenog stanja za naredni korak, ali se sljedećim korakom uvodi samo jedna nova odluka.
8. Tek nakon završetka upisati poseban `outcome` zapis.
9. Ne mijenjati domene, formule, smjerove, kriterije ili labelu nakon uvida u buduće ishode.

Decision i outcome zapisi validiraju se prema [schemas/decision_log.schema.json](schemas/decision_log.schema.json) i dodatnim vremenskim provjerama u `master_regimes.feedback_loop`.

## 8. Oznake ishoda

Oznaka se dodjeljuje nakon result-validity i noise audita:

- `positive`: trajanje ili drugi unaprijed zaključani primarni ishod se poboljšao izvan lokalnog šuma, bez jasno suprotnog fizičkog pomaka;
- `negative`: primarni ishod se pogoršao izvan šuma, bez kompenzirajućeg poboljšanja ciljanog fizičkog dokaza;
- `mixed`: ishod i fizički domeni se kreću u suprotnim smjerovima ili se domenske komponente međusobno sukobljavaju; kraće trajanje uz rast jednog ili više domena obavezno ostaje `mixed`;
- `indeterminate`: rezultat nije uporediv, dokaz je nepotpun ili je promjena unutar lokalnog mjernog šuma.

Oznaka ne mijenja sirove vrijednosti niti komponentni izvještaj.

## 9. Upiti i intervencije

[query_trajectory_manifest.yaml](query_trajectory_manifest.yaml) koristi tri postojeće analitičke namjere:

- puni agregacijski tok nad relevantnim događajima;
- join sa raw i regionalno potisnutom varijantom;
- sortiranje/Top-K kao samo jedan od tri fizička oblika.

Isti manifest zamrzava i vremenski ugovor. Generator koristi `base_time_unix=1782864000`, odnosno `2026-07-01 00:00:00 UTC`, a SQL granice su dozvoljeni cjelobrojni odmaci od tog oslonca. Datumi u renderovanom SQL-u zato nisu vezani za vrijeme pokretanja eksperimenta. Measured SQL putanja ovog protokola ne smije koristiti `now()` ili drugi zidni sat.

Intervencije dolaze iz unaprijed ograničenog [intervention_catalog.yaml](intervention_catalog.yaml). Nema dataset reload-a, promjene kolokacije, shard movementa, izgradnje indeksa ni destruktivnog DDL-a. Indeks je namjerno izostavljen iako je legitimna DBA intervencija, jer ovaj protokol traži brze i reverzibilne korake bez promjene zaključane strukture.

## 10. Dry-run i vremenski budžet

Plan sadrži:

- 3 putanje;
- 3 ponavljanja početnog stanja;
- očekivano 3 adaptivna koraka po putanji;
- najviše 4 adaptivna koraka po putanji.

Očekivano je 36, a maksimalno 45 mjerenih SQL izvršenja. Hard timeout je 900 sekundi po izvršenju, pa maksimalni zbir query timeouta iznosi 11,25 sati. Sa rollbackom, provjerama i indeksiranjem ukupni hard budžet je 14 sati.

`dry_run_plan.csv` je operativni raspored slotova, ne dozvola za izvršavanje. Svi redovi imaju `live_execution=false`.

## 11. Gate prije Taska 2

Task 2 se ne smije pokrenuti dok validator ne potvrdi:

- autoritativne RQ/H formulacije nisu promijenjene;
- postoji tačno šest domena u zamrznutom redoslijedu;
- nema globalnih pragova visokog/niskog pritiska;
- svaka akcija ima apply, rollback i obje provjere;
- decision zapis prethodi outcome zapisu;
- budući ishodi ne ulaze u trenutno stanje;
- sva tri identitetska slučaja su eksplicitna;
- dry-run broji 36 očekivanih i 45 maksimalnih izvršenja;
- plan ne zahtijeva reload dataseta, kolokaciju, shard movement ili indeks.

Komanda:

```bash
make feedback-loop-dry-run
```

Komanda samo validira ugovore, ponovo generiše CSV i zapisuje offline gate izvještaj. Ne pristupa infrastrukturi.
