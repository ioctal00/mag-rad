# Sažetak tri offline analize retrieval memorije

## Autoritativna jedinica analize

Top-1 nije testiran na samo 15 fizičkih izvršenja. Potvrdni panel sadrži 300 fizičkih izvršenja, ali ona formiraju 15 SQL odluka: za svaki SQL oblik pet puta su izmjereni baseline i tri uslova. Ponavljanja stabilizuju stvarni poredak akcija, ali ne stvaraju nove nezavisne SQL odluke.

Široki korpus sa 2.607 izvršenja ima 418 before/after parova, ali svaki od 418 početnih uslova ima samo jednu izmjerenu akciju. Zato iz njega nije moguće izračunati stvarnog pobjednika među tri akcije bez izmišljanja nedostajućih kontrafaktualnih ishoda.

Za ova tri audita koristi se najveći postojeći zajednički skup sa potpunom matricom akcija u istom zamrznutom prostoru: 26 razvojnih, 45 završnih DBA, 45 kontrolisanih topology i 15 potvrdnih stanja. To je 131 stanje sa 393 izmjerena ishoda akcija, ali samo 31 deklarisana logička grupa. Ponovljena stanja q01–q15 zato nisu predstavljena kao novi nezavisni SQL problemi.

Izvorni replay počinje sa 26 stanja jer zamrznuti ugovor upravo taj razvojni izvještaj definiše kao početnu memoriju. Preostala dva ranija panela bila su odvojeni evaluacijski dokazi. Njihovo sadašnje uključivanje provjerava osjetljivost na sastav memorije, ali ne mijenja retroaktivno finalni ugovor.

## Glavni brojevi

- Stvarni pobjednici: `{'mitigate_remote_path_bundle': 83, 'regional_topk_candidates': 48}`.
- Retrospektivna pokrivenost pri n=5: 0.531; pri n=130: 1.000.
- Top-1 kandidata bez apstinencije pri n=5: 0.524; pri n=130: 0.600.
- Među najbližih 5% svih parova isti pobjednik se javlja u 0.775 slučajeva, naspram marginalne osnove 0.532.
- Spearmanova veza state-distance i centriranog response-distance iznosi 0.003, uz stratifikovani permutacijski p=0.9074.

## Odgovor na dilemu

Nazivnik od 15 jeste malen za preciznu opću procjenu tačnosti. Rezultat 8/14 ima deskriptivni 95% Wilsonov interval [0.326, 0.786], a jedna odluka mijenja Top-1 za približno 0,071. Panel je zato dovoljan da pokaže da se raniji pozitivan rezultat nije ponovio na ovih 15 novih oblika, ali nije dovoljan da procijeni univerzalnu tačnost.

Slučajevi iz iste nove populacije mogu pomoći: sa 26 razvojnih i 14 drugih potvrdnih slučajeva retrospektivni Top-1 kandidata dostiže 0.667, a regret pada na 0.253. To odgovara 10/15 tačnih odluka, ali koristi naknadno poznate ishode. Važniji test sastava memorije pokazuje da svih 116 ranijih potpunih stanja pokriva 15/15 ciljeva, ali daje samo 7/15 tačnih kandidata. Kada se dodaju i ishodi ostalih 14 potvrdnih slučajeva, rezultat je 9/15. Veća memorija je zato riješila fizičku nepokrivenost, ali nije monotono riješila izbor akcije.

Unutar P99 nalazi se 81 par između potvrdnog i svih ranijih panela, dok Spearmanova veza udaljenosti poretka akcija za te parove iznosi -0.035. Premala memorija jeste dio problema pokrivenosti, ali nije jedini problem. P64→6 fizička geometrija samo slabo prati geometriju odziva na intervenciju.

## Granice

Ovo nisu novi infrastrukturni eksperimenti niti nova finalna evaluacija. Retrospektivna kriva koristi kasnije poznate slučajeve samo da razdvoji problem pokrivenosti od problema akcijskog odziva. Uz to, razvojnih 26 stanja predstavljaju parametrizacije jedne logičke Top-K namjere, a završni DBA i topology paneli ponavljaju q01–q15 u kontrolisanim kontekstima. Nijedan od 131 slučaja nema `work_mem` kao strogog pobjednika. Zaključci su zato ograničeni na ovaj konkretni P64→6 ugovor, dvije opažene pobjedničke akcije i postojeću infrastrukturu.

## Datoteke

- `01-learning-coverage-curve.md`
- `02-neighbor-consistency.md`
- `03-state-response-geometry.md`
- `prior_panel_memory_comparison.csv`
- `broad_corpus_action_matrix_audit.csv`
- `case_catalog.csv`, `pairwise_distances.csv` i ostali pomoćni CSV/JSON izlazi
- `inputs/`: tačni ulazni redovi iz razvojnog, završnog DBA, topology i širokog korpusa
- `source/116_retrieval_density_geometry_audit.py`: skripta korištena za ovaj audit

## Ponovno računanje

Iz korijena javnog paketa pokreće se `make retrieval-density-audit`. Komanda ne pristupa bazi, ne izvršava SQL i ne refituje zamrznutu reprezentaciju. Rezultate zapisuje u `build/retrieval-density-geometry-audit-v1/`, tako da autoritativni release ostaje nepromijenjen.
