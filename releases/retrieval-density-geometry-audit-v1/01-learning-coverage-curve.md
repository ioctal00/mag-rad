# Analiza 1: veličina memorije, pokrivenost i kvalitet odluke

## Pitanje

Da li veći broj kompletnih slučajeva poboljšava samo pokrivenost zamrznute P64→6 memorije ili i sposobnost razlikovanja najbolje intervencije?

## Podaci i postupak

Analiza koristi svih 131 postojećih stanja sa kompletnom matricom tri akcije: 26 razvojnih, 45 završnih DBA, 45 iz kontrolisanog topology panela i 15 potvrdnih. P64→6 transformacija ostaje fitovana samo na 26 razvojnih stanja, iz kojih je izvedena i P99 granica. Za svaki od 15 potvrdnih ciljeva nasumično se uzima n slučajeva među preostalih 130, uz 2.000 ponavljanja po veličini memorije. Ovaj test može uključiti ponovljene q01–q15 slučajeve i kasnije potvrdne ishode. Zato nije nova holdout procjena, nego dijagnostika gustoće i sastava memorije.

Objavljeni strogi i vremenski replay počinju sa 26 razvojnih stanja zato što ih zamrznuti `model_freeze.reference_report` ugovor eksplicitno imenuje kao početnu memoriju. Završni DBA i topology paneli zadržani su kao odvojeni evaluacijski dokazi. Njihovo uključivanje u ovom auditu jeste post-hoc osjetljivost i ne zamjenjuje unaprijed definisani rezultat.

Zamrznuta granica pokrivenosti iznosi 1.953355.

## Retrospektivna kriva gustoće

| n | Pokrivenost | Top-1 izdatih | Regret izdatih | Top-1 bez apstinencije | Regret bez apstinencije |
| --- | --- | --- | --- | --- | --- |
| 5 | 0.531 | 0.530 | 0.445 | 0.524 | 0.453 |
| 10 | 0.781 | 0.545 | 0.414 | 0.544 | 0.422 |
| 15 | 0.902 | 0.545 | 0.415 | 0.547 | 0.417 |
| 20 | 0.958 | 0.532 | 0.446 | 0.534 | 0.445 |
| 30 | 0.991 | 0.539 | 0.449 | 0.539 | 0.450 |
| 40 | 0.999 | 0.559 | 0.421 | 0.559 | 0.421 |
| 60 | 1.000 | 0.595 | 0.368 | 0.595 | 0.368 |
| 80 | 1.000 | 0.610 | 0.355 | 0.610 | 0.355 |
| 100 | 1.000 | 0.619 | 0.353 | 0.619 | 0.353 |
| 116 | 1.000 | 0.618 | 0.365 | 0.618 | 0.365 |
| 130 | 1.000 | 0.600 | 0.391 | 0.600 | 0.391 |

Top-1 među izdatim preporukama zavisi od apstinencije. Kolona bez apstinencije zato prikazuje kvalitet kandidata i kada je najbliži slučaj izvan P99 granice.

## Sastav već postojeće historije

Broj slučajeva nije dovoljan opis memorije. Sljedeći post-hoc replay uspoređuje različite već izmjerene panele bez refitovanja reprezentacije:

| Sastav memorije | n | Preporuke | Pokrivenost | Tačno | Top-1 kandidata | Regret kandidata | Medijalni najbliži d |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 26 razvojnih | 26 | 0 | 0.000 | 8 | 0.533 | 0.389 | 5.005 |
| + 45 završnih DBA | 71 | 0 | 0.000 | 8 | 0.533 | 0.389 | 4.957 |
| + 45 topology | 71 | 15 | 1.000 | 7 | 0.467 | 0.626 | 0.829 |
| svih 116 ranijih | 116 | 15 | 1.000 | 7 | 0.467 | 0.626 | 0.829 |
| 116 + 14 drugih potvrdnih | 130 | 15 | 1.000 | 9 | 0.600 | 0.391 | 0.339 |

## Dopunjavanje zamrznute memorije novim kohortom

Ova odvojena osjetljivost zadržava 26 razvojnih stanja i dodaje od 0 do 14 drugih potvrdnih slučajeva. Ona namjerno pokazuje šta bi se dogodilo kada bi memorija već sadržavala slučajeve iz iste nove populacije. Nikada ne koristi vlastiti ishod cilja:

| Stari slučajevi | Novi slučajevi | Ukupno | Pokrivenost | Top-1 izdatih | Top-1 bez apstinencije | Regret bez apstinencije |
| --- | --- | --- | --- | --- | --- | --- |
| 26 | 0 | 26 | 0.000 |  | 0.533 | 0.389 |
| 26 | 1 | 27 | 0.895 | 0.543 | 0.557 | 0.356 |
| 26 | 2 | 28 | 0.983 | 0.563 | 0.563 | 0.373 |
| 26 | 3 | 29 | 0.998 | 0.540 | 0.540 | 0.409 |
| 26 | 5 | 31 | 1.000 | 0.522 | 0.522 | 0.451 |
| 26 | 8 | 34 | 1.000 | 0.616 | 0.616 | 0.320 |
| 26 | 10 | 36 | 1.000 | 0.636 | 0.636 | 0.295 |
| 26 | 14 | 40 | 1.000 | 0.667 | 0.667 | 0.253 |

## Strogo vremenski replay

U stvarnom redoslijedu memorija počinje sa 26 razvojnih stanja. Nakon svake odluke otkrivaju se tri već izmjerena ishoda tog slučaja. Izdato je 14/15 preporuka, od kojih je 8/14 bilo tačno. Srednji regret izdatih preporuka bio je 0.352 log2. Ovo tačno reprodukuje objavljeni prequential rezultat. Deskriptivni 95% Wilsonov interval za 8/14 iznosi [0.326, 0.786]. On pokazuje veliku nesigurnost omjera, ali nije interval univerzalne produkcijske tačnosti jer 15 SQL oblika nisu slučajan uzorak takve populacije.

## Zaključak

Uniformna kriva od n=5 do n=130 povećava pokrivenost za +0.469, a Top-1 kandidata za +0.076. Kada se svih 26 starih slučajeva dopuni sa 14 slučajeva iz novog kohorta, pokrivenost raste sa 0.000 na 1.000, a Top-1 kandidata sa 0.533 na 0.667. Pokrivenost se zasićuje ranije od diskriminacije akcija. Top-1 pritom nije monotona funkcija broja slučajeva: sa tri do pet novih slučajeva privremeno opada jer se mijenja sastav pet najbližih susjeda. Veća lokalna memorija iz istog kohorta na kraju pomaže, ali ni taj povoljniji replay ne prelazi 10/15 tačnih odluka.

Još važnije, svih 116 slučajeva dostupnih prije potvrdnog panela daju pokrivenost 1.000, ali samo 7/15 tačnih kandidata i regret 0.626. Kada se dodaju i svih 14 drugih potvrdnih slučajeva, rezultat je 9/15, a ne monotono poboljšanje. Oskudnost podataka je dio problema pokrivenosti, ali sastav memorije i odnos fizičke sličnosti prema odzivu ostaju zaseban problem.

Kriva se ne smije tumačiti kao procjena buduće produkcijske tačnosti, jer je post-hoc i sadrži ponovljena stanja istih q01–q15 upita.
