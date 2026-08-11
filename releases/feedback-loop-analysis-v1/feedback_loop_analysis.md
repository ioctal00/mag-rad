# Analiza adaptivnog feedback loopa i zamrznutog replaya

## Ugovor analize

Analiza koristi samo završene artefakte. RQ1–RQ4, H1–H4, šest domena, odluke i kriteriji ishoda nisu mijenjani. Zamrznuti prostor `93 → 64 → 6` primijenjen je bez refitovanja, a nedostupan dokaz ostaje `NA`.

Domenske koordinate su **relativna izraženost dokaza o pritisku** prema lokalnoj referenci. Njihov broj, apsolutna veličina, uzročnost i end-to-end dobitak nisu ista veličina.

## Hronološke putanje

```text
Exact aggregate: A --fdw_fetch_size_10000--> B --regional_pushdown_rewrite--> C --wan_delay_10ms_probe--> D --rollback--> A'
Join/pushdown: R0 --regional_pushdown_rewrite--> R1 --fdw_async_capable_on--> R2 --rollback--> R0'
Top-K:        R0 --gac_work_mem_64mb--> R1 --regional_pushdown_rewrite--> R2 --wan_delay_10ms_probe--> R3 (odbačeno) --rollback--> R0'
Replay:       A  --gac_work_mem_64mb--> B  --regional_pushdown_rewrite--> C  --wan_delay_10ms_probe--> D
```

Odluke adaptivne faze trajno su zapisane prije ishoda. Replay je koristio zamrznut redoslijed i nije vraćao ishode u odluke.

## Glavni tranzicijski nalazi

- Pet adaptivnih tranzicija sačuvalo je rezultat; tri su ponovljene u zamrznutom Williams replayu. Odvojeni exact-aggregate dodatak sadrži tri potvrđujuće tranzicije i završni rollback, po pet ponavljanja svakog stanja.
- U exact aggregate putanji `fetch_size` je bio pozitivan (`g=0.198`) uz oskudnu fizičku tranziciju, regionalni COUNT/MIN/MAX pushdown snažno pozitivan (`g=3.579`) i fizički mješovit, a WAN +10 ms negativan (`g=-0.347`) uz oskudnu fizičku tranziciju.
- Regionalni rewrite skratio je join sa 18,551 s na 3,319 s (`g=2,483`) i Top-K sa 15,808 s na 5,767 s (`g=1,455`). Više domena se promijenilo istovremeno, pa se dobitak ne pripisuje jednoj koordinati.
- `fdw_async_capable_on` promijenio je manje dostupnih koordinata, ali dodatno skratio join sa 3,319 s na 2,240 s (`g=0,567`).
- GAC `work_mem` dao je mali, razriješen dobitak u adaptivnoj fazi (`g=0,157`) i replayu (`g=0,204`), uz smanjenje GAC temp zapisa i hash-batch viška. Ovo nije primjer fizičke promjene bez runtime efekta.
- Namjerni WAN probe pogoršao je trajanje (`g=-0,905` adaptivno; hronološki replay `g=-0.962`) i bio je odbačen.
- Široki korpus, a ne ova mala putanja, nosi primjer uklonjenog spill-a ili skewa bez značajnog globalnog dobitka.

## Stabilnost

- Zamrznuti replay ima 20/20 rezultatski ekvivalentnih izvršenja.
- Exact aggregate dodatak ima 25/25 ekvivalentnih izvršenja sa istim uređenim i multiskupovnim hashom. COUNT/MIN/MAX rezultat koristi tačnu aritmetiku i ne oslanja se na post-hoc toleranciju.
- Join i Top-K rollback vraćaju sve dostupne koordinate na početni profil; trajanja ostaju unutar početnog noise envelopea. Novi exact aggregate rollback vraća konfiguraciju, mrežni profil, rezultat i fizički profil, a runtime interval uključuje nultu promjenu.
- Smjer sva tri zamrznuta efekta jednak je eksplorativnom zaključku: `work_mem` mali pozitivan, pushdown snažno pozitivan, WAN delay negativan.

## Lokalna memorija tranzicija

Vremenski replay izdaje 4 procjena i 4 apstinencija. Koristi samo ranije opažene ishode iste akcije. Nedostajući ishodi nisu nule.

- Direktna memorija istog `logical_question_id` dostupna je za 3 zamrznute tranzicije i zadržava smjer u 3/3 slučaja.
- Ručno povezane SQL varijante omogućavaju da raw i regionalno reducirani SQL ostanu u istoj putanji uprkos različitom normalizovanom SQL hash-u.
- Cross-query fizički retrieval javlja se samo u 1 dovoljno ranom action-matched slučaju. Smjer je koristan, ali jedan slučaj nije dokaz opće generalizacije.

## Zamrznuti PCA i prototipski audit

Zamrznuti R3 artefakt ima 93 kandidata, 64 aktivna pokazatelja i 6 PCA komponenti. Fit obuhvata 26 ranijih razvojnih stanja; feedback stanja korištena za fit: 0. P99 prag ostaje 1.953355.

Od 15 novih stanja, 0 je unutar zamrznute P99 granice. K-means zadržava isti tvrdi prototip kroz 8/8 tranzicija. To je kompresija geometrije, ne dokaz da je tranzicija fizički ili operativno beznačajna.

FCM članstva mogu pokazati meku promjenu prema više razvojnih prototipa, ali ne čuvaju eksplicitno akciju, hronologiju, sirove komponente ni prije/poslije ishod. Zbog toga ostaju sekundarni audit RQ2/RQ3/H2, a ne zamjena za tranzicijski zapis.

## Status fiksnih pitanja i hipoteza

Detaljna mapa je u `rq_hypothesis_evidence_map.csv`. Feedback loop daje longitudinalni dokaz za RQ2/H1/H3 i lokalnu granicu za RQ3, ali ne mijenja nijednu formulaciju niti pretvara fizički mješovit rezultat u univerzalnu potvrdu. Valjanost rezultata, end-to-end učinak i fizička tranzicija prijavljuju se kao tri nezavisne ose.

## Otvorena ograničenja

- Izvorna aggregate putanja ostaje validity stop jer zamrznuti ugovor nije sadržavao numeričku toleranciju za zadnje bitove `double precision` prikaza. Odvojeni unaprijed zamrznuti exact COUNT/MIN/MAX dodatak popunjava longitudinalni dokaz bez izmjene tog historijskog ishoda.
- `repartition_locality` je u ovim putanjama uglavnom `NA`; nije imputiran kao nizak pritisak.
- Feedback studija je mala, lokalna i adaptivna. Potvrđuje ponovljivost izabranih tranzicija, ne optimalnost LLM odluka među svim PostgreSQL/Citus mogućnostima.
- Collector i intervencijski ugovor action-agnostic su po konstrukciji, a primjenjivost je demonstrirana nad evaluiranim SQL, konfiguracijskim, FDW i mrežnim promjenama na jednoj infrastrukturi. Automatski transfer na nepoznate SQL oblike, akcije i infrastrukture nije potvrđen.
- Ne postoji pošten feedback-loop primjer fizičke promjene bez razriješenog runtime dobitka; taj zaključak se oslanja na unaprijed odvojeni široki korpus.
