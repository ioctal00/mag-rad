# Mapa feedback-loop eksperimenta prema fiksnim RQ1–RQ4 i H1–H4

Formulacije u ovom dokumentu doslovno su preuzete iz prijave teme. Ne predstavljaju novu verziju pitanja ili hipoteza.

## Autoritativna istraživačka pitanja

**RQ1.** Koji normalizovani pokazatelji nakon izvršavanja najdosljednije opisuju režime izvršavanja globalnih analitičkih SQL upita pri promjeni veličine skupa podataka, WAN profila, profila neravnomjernosti rada i konfiguracijskih parametara?

**RQ2.** Može li neizrazito grupisanje nad normalizovanim mjernim pokazateljima izdvojiti interpretabilne režime izvršavanja globalnih analitičkih SQL upita?

**RQ3.** Da li raspodijeljeni stepen pripadnosti režimima bolje opisuje mješovite slučajeve izvršavanja od tvrdog dodjeljivanja jednom režimu?

**RQ4.** Koji pokazatelji najviše doprinose razlikovanju dobijenih režima i kako se ti režimi mogu povezati sa arhitektonskim tumačenjima?

## Autoritativne hipoteze

**H1.** Relativni i normalizovani pokazatelji, kao što su udjeli vremena izvršavanja, faktor redukcije podataka (DRF), globalni priliv rezultata, faktor neravnomjernosti rada i spill signal, daju interpretabilnije režime od apsolutnih metrika kao što su ukupno vrijeme izvršavanja ili apsolutni broj prenesenih redova.

**H2.** Neizrazito grupisanje bolje opisuje mješovite režime izvršavanja od tvrdog grupisanja, jer omogućava da jedno izvršenje SQL upita bude opisano raspodijeljenim stepenom pripadnosti režimima.

**H3.** Slični režimi izvršavanja pojavljuju se pri kontrolisanoj promjeni veličine skupa podataka, WAN profila i profila neravnomjernosti rada, što ukazuje da režimi nisu samo artefakt jedne eksperimentalne konfiguracije.

**H4.** U scenarijima sa regionalnom neravnomjernošću rada ili nekolociranim spajanjima tabela, kompaktan WAN izlaz nije dovoljan indikator ukupnog ponašanja SQL upita, jer regionalna obrada ili premještanje podataka mogu ostati dominantni faktori režima izvršavanja.

## Operacionalizacija bez novog pitanja

| Ugovor iz prijave | Uloga feedback-loop eksperimenta | Dozvoljena tvrdnja |
| --- | --- | --- |
| RQ1 | Manifest zamrzava ulazne pokazatelje, porijeklo, NA pravila i tri lokalne reference. | Task 1 definiše reproducibilan relativni profil; ne daje novi empirijski odgovor bez Taska 2. |
| RQ2 | Šestodimenzionalna stanja i njihove tranzicije postaju ulaz za postojeći FCM postupak. | Ispituje se može li neizrazito grupisanje sažeti lokalne putanje u interpretabilne prototipe. |
| RQ3 | Za stanja sa konfliktom više domena porede se fuzzy pripadnosti i tvrda dodjela. | Daje dodatni lokalni dokaz o tome da li raspodijeljena pripadnost čuva mješovitu promjenu. |
| RQ4 | Komponente domenskih koordinata ostaju auditabilne; FCM i tvrda prototipska kompresija porede se po gubitku komponentnog i tranzicijskog dokaza. | RQ4 ostaje pitanje doprinosa pokazatelja i arhitektonskog tumačenja, ne action recommender pitanje. |
| H1 | Za svako stanje čuvaju se raw apsolutne vrijednosti i relativni profil prema origin/previous/history referenci. | Omogućava direktno offline poređenje apsolutnog i relativnog opisa bez promjene definicije nakon ishoda. |
| H2 | FCM se poredi sa tvrdom dodjelom na istim stanjima. | Feedback loop ne pretpostavlja da je H2 potvrđena; zadržava je kao originalnu komparativnu hipotezu. |
| H3 | Putanje koriste kontrolisane reverzibilne promjene WAN i konfiguracijskih parametara; dataset i skew se u ovom dodatku ne mijenjaju. | Može dati dodatni lokalni dokaz za podskup H3, ali ne novu potvrdu cijele hipoteze. |
| H4 | Join putanja zadržava regionalne, repartition i WAN komponente iako se u Tasku 1 ne mijenjaju kolokacija ni shard placement. | Postojeći H4 dokaz ostaje nepromijenjen; novi profil samo čuva potrebnu observability vezu. |

## Granice

- `action_id` nije novo istraživačko pitanje i nije target za automatski izbor.
- Broj aktivnih domena je deskriptivan i ne zamjenjuje fuzzy pripadnost.
- Task 1 ne izvršava SQL i zato ne proizvodi novi empirijski status RQ/H.
- Task 2 ne smije promijeniti formulacije, domene ili kriterije nakon prvog ishoda.
