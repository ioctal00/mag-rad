# Prijedlog izmjena rukopisa po sekcijama

## Metodologija

- Nakon formalne epizode uvesti lokalni profil `R_t` sa šest zamrznutih domena i tranziciju `tau_t=(R_t, action_id, R_t+1, delta_outcome_t)`.
- Jednom definisati da je koordinata relativna prema originu, prethodnom prihvaćenom stanju ili ranijoj lokalnoj historiji; nije univerzalni severity score.
- Dodati pravilo vremenski korektne memorije: logical question, zatim isti normalizovani SQL u kompatibilnom kontekstu, zatim fizički cross-query slučajevi kao sekundarni sloj.
- FCM/K-means ostaviti kao razvojne/projekcijske komparatore, bez refita finalnog R3 prostora.

## Eksperimentalni dizajn

- Promijeniti pregled sa pet na šest dokaznih blokova i dodati feedback loop kao drugi glavni blok.
- Navesti samo stvarno izvršene akcije: `fetch_size`, regionalni pushdown rewrite, `fdw_async_capable`, GAC `work_mem` i kontrolisani WAN delay.
- Razdvojiti adaptivnu fazu, zamrznuti Williams replay i unaprijed zamrznuti exact-aggregate dodatak. Historijski floating-point stop zadržati kao validity case.

## Rezultati

- Nakon širokog korpusa postaviti feedback loop kao vodeću longitudinalnu studiju.
- Prvo prikazati heatmap šest domena i hronološku tabelu tranzicija; zatim stabilnost, rollback i vremenski korektnu lokalnu memoriju.
- Valjanost rezultata, end-to-end učinak i fizičku tranziciju prikazati kao tri nezavisne ose; legacy oznaku `mixed` ne koristiti kao glavni rezultat.
- Top-K full-information paneli ostaju sekundarna kontrolisana evaluacija RQ3; potvrdni negativni rezultat ostaje granica cross-query transfera.
- Jasno navesti da u longitudinalnoj studiji nema primjera fizičke promjene bez razriješenog runtime efekta; primjer dolazi iz širokog korpusa.

## Diskusija

- Objediniti ograničenja u jednu završnu podsekciju.
- Razdvojiti broj promijenjenih domena, relativnu izraženost dokaza, uzročnost i runtime korist.
- RQ3 razložiti na direktnu memoriju, ručno povezane SQL varijante i ograničeni fizički cross-query transfer.
- FCM komprimirati na jedan rezultat: prototip sažima geometriju, ali zamagljuje hronologiju i action-specific ishod.

## Zaključak

- Dodati longitudinalnu tranziciju kao centralni empirijski dokaz između širokog korpusa i sekundarnog recommender eksperimenta.
- Zadržati postojeće RQ1–RQ4 i H1–H4 doslovno; ne dodavati novo pitanje.
