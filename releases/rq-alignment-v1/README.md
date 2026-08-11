# Historical RQ alignment v1, superseded

This directory preserves the earlier F21-development tables for audit history. It is not the authoritative RQ1-RQ4 package used by the current thesis. Use [`../rq-alignment-v2/`](../rq-alignment-v2/) for the promoted F19 model.

Ovaj paket konsoliduje zamrznute offline dokaze potrebne za direktne odgovore na fiksna RQ1--RQ4. Ne refituje FCM, ne mijenja izbor pokazatelja i ne koristi ishode novih infrastrukturnih eksperimenata.

## Autoritativni izvori u ovom paketu

- The files below describe the historical 21-feature development space. The semantic-v2 contract defines 19 features and belongs to the replacement F19 package, not to these CSV files.
- [`rq1_feature_space_audit.csv`](rq1_feature_space_audit.csv) i [`rq2_fcm_model_audit.csv`](rq2_fcm_model_audit.csv) cuvaju razvojna poredjenja prostora i broja prototipa.
- [`rq2_fcm_prototypes.csv`](rq2_fcm_prototypes.csv), [`rq3_mixed_case_memberships.csv`](rq3_mixed_case_memberships.csv) i [`rq3_mixed_case_feature_support.csv`](rq3_mixed_case_feature_support.csv) cuvaju profile prototipa i stvarni mjesoviti slucaj prikazan u rukopisu.
- [`analysis/reports/fuzzy-intervention-memory-v1/`](../../analysis/reports/fuzzy-intervention-memory-v1/) cuva audit izbora pokazatelja za odvojeni sekundarni prostor pretrage.

Historijski identiteti izvornog dijagnostickog izlaza ostaju u CSV redovima zbog sljedivosti. Za citanje i ponovno racunanje tabela RQ1--RQ4 nije potreban odvojeni rukopisni repozitorij niti nedostupna lokalna Git historija.

## Granice tumačenja

- FCM prototipi su opisni geometrijski sažeci, ne ground-truth klase i ne nezavisni intenziteti fizičkih pritisaka.
- `support` je razlika kvadriranih udaljenosti obilježja do vodećeg i konkurentskog centra. Nije fizička vrijednost niti kauzalni doprinos.
- NMI audit podržava manju zavisnost konačnog prostora od identiteta skupa podataka u posmatranom korpusu; ne dokazuje univerzalnu invarijantnost.
- Mješoviti slučaj pokazuje da fuzzy članstvo čuva sekundarnu geometrijsku sličnost. Downstream poređenje nije pokazalo dosljednu operativnu prednost fuzzy kompresije.

## Datoteke

- `rq1_feature_families.csv`: imenovane porodice i pokazatelji.
- `rq1_feature_space_audit.csv`: razvojni audit tri prostora.
- `rq2_fcm_model_audit.csv`: izbor broja prototipa i fuzzy stabilnost.
- `rq2_fcm_prototypes.csv`: zamrznuta opisna imena i tumačenja.
- `rq3_mixed_case_memberships.csv`: stvarna raspodjela članstva jednog mješovitog izvršenja.
- `rq3_mixed_case_feature_support.csv`: najveći lokalni doprinosi prema dva vodeća prototipa.
- `rq3_threshold_audit.csv`: udio jasnih, mješovitih i slabo pokrivenih izvršenja.
- `rq4_feature_contribution_summary.csv`: veza porodica sa arhitekturom i kriterijem doprinosa.
