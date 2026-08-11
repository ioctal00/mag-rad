---
name: navigate-master-thesis
description: Navigate and explain the master's thesis, its SQL queries, datasets, experiments, models, results, figures, source code, and reproducibility artifacts. Use when a user asks where a thesis-related item is located, what an artifact contains, how it was produced or used in the thesis, which conclusion it supports, or how several thesis concepts and experiments relate to each other.
---

# Navigate Master Thesis

## Cilj

Pomoći korisniku da pronađe bilo koji pojam ili artefakt rada, objasniti njegovu strukturu i ulogu te zatim neposredno odgovoriti na korisnikovo pitanje.

Rad razvija provjerljiv postupak za povezivanje GAC, FDW, regionalnih Citus i worker/task dokaza jednog SQL izvršenja. Povezana izvršenja prije i poslije DBA intervencije čuvaju provjeru rezultata, fizičke promjene, trajanje i porijeklo dokaza. FCM opisuje fizičke obrasce, dok je automatska ponovna upotreba iskustva sekundarna i ograničena analiza.

## Obavezna karta

Prije pretrage pročitaj [`references/THESIS_MAP.md`](references/THESIS_MAP.md). Ona definiše autoritativne putanje, eksperimentalne jedinice, numeričke poglede i česte zamke identiteta.

Odredi `PACKAGE_ROOT` kao korijen repozitorija koji sadrži `START_HERE.md` i `config/release-spec.json`. Kada je vještina u izvornom javnom paketu, to je direktorij dva nivoa iznad `SKILL.md`. Ako je vještina instalirana odvojeno, pronađi checkout `master-thesis-final` prije odgovora.

## Postupak

1. Razvrstaj upit kao pojam, SQL, dataset, eksperiment, rezultat, model, figura/tabela, konfiguracija, izvorni kod ili provjera ponovljivosti.
2. Počni od najužeg indeksa navedenog u karti. Nemoj odmah pretraživati svih nekoliko hiljada fajlova.
3. Razriješi puni identitet. Za SQL navedi puni naziv, corpus/panel i varijantu. Za model razlikuj `R6`, `F19`, `F21-dev` i `P64->6`.
4. Otvori autoritativni CSV, JSON, YAML, SQL ili manifest. Prozni README koristi za navigaciju, ne kao jedini dokaz numeričke tvrdnje.
5. Ako je dostupan sibling repozitorij `master-regimes-thesis`, pronađi mjesto u rukopisu i objasni kako je artefakt korišten. Inače koristi claim-evidence mapu i release ugovor.
6. Provjeri jedinicu procjene i vremenski redoslijed prije tumačenja brojeva.
7. Odgovori na stvarno pitanje korisnika, a ne samo spiskom putanja.

## Pravila integriteta

- Ne izjednačavaj `q07` ili sličnu kratku oznaku kroz različite corpuse. Puni naziv i corpus su dio identiteta.
- Ne predstavljaj 300 fizičkih izvršenja potvrdnog panela kao 300 nezavisnih odluka. Ona stabilizuju ishode 15 SQL oblika.
- Ne miješaj završni `F19`, historijski `F21-dev`, relativni profil `R6` i PCA prostor `P64->6`.
- Ne nazivaj razvojni/reference panel finalnim holdoutom.
- Ne predstavljaj fizičku blizinu kao dokaz jednakog odziva na intervenciju.
- Ne tretiraj nedostajući ili neprimjenjiv dokaz kao nulu.
- Ne tvrdi da korisnik ili sistem automatski razumije semantičku ekvivalentnost SQL-a. `logical_question_id` je deklarisana veza uz provjeru rezultata.
- Ne pokreći SQL ili infrastrukturu radi običnog navigacijskog pitanja. Koristi objavljene artefakte, osim ako korisnik izričito traži novi run.
- Ako dokaz nije objavljen, reci šta nedostaje i ne popunjavaj prazninu pretpostavkom.

## Oblik odgovora

Prilagodi dužinu pitanju, ali u pravilu uključi:

1. **Kratak odgovor** na korisnikovo pitanje.
2. **Gdje se nalazi**, sa jednom do tri najkorisnije putanje.
3. **Šta artefakt sadrži**, uključujući važne identitete ili kolone.
4. **Kako je korišten u radu**, odnosno kojem toku dokaza, RQ-u ili studiji pripada.
5. **Šta se smije zaključiti**, zajedno sa važnim ograničenjem kada postoji.

Kada postoji više kandidata, prvo objasni razliku pa zatraži dodatni identitet samo ako je i dalje nužan.
