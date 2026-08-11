# Ispravka R6 domene reparticionisanja i lokalnosti

Ova napomena opisuje ispravku izvedenog prikaza šeste domene longitudinalnog profila. Ne mijenja izvorna SQL izvršenja, planove, rezultate niti arhivirani release `feedback-loop-analysis-v1`.

Naknadni offline audit pokazao je da je tekstualna vrijednost `false` za `citus_repartition_observed_v2` bila izgubljena pri numeričkoj konverziji. Kategorička vrijednost lokalnosti bila je zasebno izgubljena pri pokušaju numeričke agregacije. Izvorni planovi su ipak bili dostupni i uspješno parsirani.

Provjereni nalaz je:

- svih 84 query runova ima `citus_repartition_observed_v2=false`;
- svih 84 query runova ima MapMerge broj jednak nuli;
- svih 184 regionalna planska fragmenta ima `parse_status=ok` i `parse_confidence=high`;
- zavisni map/merge i fan-out brojevi ostaju nedostupni jer MapMerge graf nije opažen;
- klasa lokalnosti je `colocated_join_candidate` u 6, a `distributed_task_plan` u 78 query runova.

Zato korigovana numerička koordinata R6 iznosi nula. To je opaženo odsustvo reparticionisanja, a ne imputacija nedostajućeg dokaza. Klasa lokalnosti ostaje kategorički kontekst i ne pretvara se u broj.

Ispravka ne utiče na trajanja, hash provjere rezultata, F19, P64->6, kNN niti ostalih pet R6 domena. Korigovani prijelazi i figure nalaze se u [`releases/feedback-loop-r6-correction-v1/`](../releases/feedback-loop-r6-correction-v1/), a izvorni arhivirani prikaz ostaje dostupan radi sljedivosti.
